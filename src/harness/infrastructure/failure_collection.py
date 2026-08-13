from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import timedelta

from harness.domain.schemas.api_execution_reporting import parse_api_execution_plan_json
from harness.domain.schemas.execution_evidence import load_execution_evidence
from harness.domain.schemas.log_evidence import (
    CollectFailureLogsCommand,
    CollectFailureLogsResult,
    FailureLogCollection,
    LogEvidenceBundle,
    LogEvidenceStats,
    LogQueryRequest,
    LogQueryResult,
    ProviderDiagnostic,
)
from harness.domain.schemas.trace_evidence import (
    CollectFailureEvidenceCommand,
    CollectFailureEvidenceResult,
    FailureEvidenceCollection,
    TraceQueryRequest,
)
from harness.infrastructure.api_execution_snapshot import ExecutionSourceSnapshotResolver
from harness.infrastructure.api_published_source import PublishedApiSourceResolver
from harness.infrastructure.failure_logs import (
    PRODUCTION_LIKE,
    LocalFileLogProvider,
    LogProvider,
    LokiLogProvider,
)
from harness.infrastructure.failure_traces import (
    LocalTraceProvider,
    build_trace_evidence,
)
from harness.infrastructure.persistence.common import create_only_json
from harness.infrastructure.persistence.filesystem import FilesystemStore


class FilesystemFailureEvidenceCollector:
    def __init__(self, store: FilesystemStore, config) -> None:
        self._store = store
        self._config = config
        self._snapshots = ExecutionSourceSnapshotResolver(store, PublishedApiSourceResolver(store))

    def collect_logs(self, command: CollectFailureLogsCommand) -> CollectFailureLogsResult:
        result = self.collect(
            CollectFailureEvidenceCommand(
                workspace_id=command.workspace_id,
                execution_id=command.execution_id,
                case_id=command.case_id,
                source="logs",
            )
        )
        collections = [
            FailureLogCollection(
                collection_id=item.collection_id,
                case_id=item.case_id,
                dataset_id=item.dataset_id,
                log_collection_status=item.log_collection_status,
                collection_path=item.collection_path,
                log_evidence_path=item.log_evidence_path or "",
            )
            for item in result.collections
        ]
        return CollectFailureLogsResult(
            workspace_id=result.workspace_id,
            execution_id=result.execution_id,
            collections=collections,
            succeeded=sum(item.log_collection_status == "success" for item in collections),
            empty=sum(item.log_collection_status == "empty" for item in collections),
            failed=sum(item.log_collection_status == "failed" for item in collections),
        )

    def collect(self, command: CollectFailureEvidenceCommand) -> CollectFailureEvidenceResult:
        snapshot = self._snapshots.resolve(command.workspace_id, command.execution_id)
        environment = snapshot.environment.casefold()
        if environment in PRODUCTION_LIKE:
            raise PermissionError("failure evidence collection is not allowed for this environment")
        selected = ["logs", "traces"] if command.source == "all" else [command.source]
        self._validate_selected_sources(selected, environment)
        workspace_root = self._store.require_workspace(command.workspace_id).resolve()
        execution_root = (workspace_root / "executions" / command.execution_id).resolve()
        evidence_path = execution_root / "evidence.json"
        manifest = json.loads((execution_root / "manifest.json").read_text(encoding="utf-8"))
        evidence_bytes = evidence_path.read_bytes()
        evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()
        if manifest.get("evidence_sha256") != evidence_sha:
            raise ValueError("execution evidence hash does not match manifest")
        evidence = load_execution_evidence(evidence_bytes)
        if (
            evidence.run_id != command.execution_id
            or evidence.environment.name != snapshot.environment
            or evidence.source_cases_path != snapshot.source_history_path
        ):
            raise ValueError("execution evidence identity differs from execution plan")
        plan = parse_api_execution_plan_json(
            (execution_root / "execution-plan.json").read_text(encoding="utf-8")
        )
        plan_case_ids = {item.case_id for item in plan.cases}
        eligible = [
            item
            for item in evidence.cases
            if item.case_id in plan_case_ids
            and (item.status == "failed" or (item.status == "error" and item.request_dispatched))
            and (command.case_id is None or item.case_id == command.case_id)
        ]
        if not eligible:
            raise ValueError("no eligible failed or dispatched-error case instances")
        collections = [
            self._collect_case(
                command,
                selected,
                case,
                snapshot.service,
                environment,
                evidence_sha,
                workspace_root,
                execution_root,
            )
            for case in eligible
        ]
        return CollectFailureEvidenceResult(
            workspace_id=command.workspace_id,
            execution_id=command.execution_id,
            collections=collections,
            succeeded=sum(
                item.log_collection_status == "success" or item.trace_collection_status == "success"
                for item in collections
            ),
            empty=sum(
                item.log_collection_status == "empty" or item.trace_collection_status == "not_found"
                for item in collections
            ),
            failed=sum(
                all(
                    status in {"failed", "unavailable"}
                    for status in (item.log_collection_status, item.trace_collection_status)
                )
                for item in collections
            ),
        )

    def _validate_selected_sources(self, selected: list[str], environment: str) -> None:
        if "logs" in selected and self._config.logs.provider != "none":
            if environment not in self._config.logs.allowed_environments:
                raise PermissionError("failure log collection is not allowed for this environment")
        if "traces" in selected and self._config.traces.provider != "none":
            if environment not in self._config.traces.allowed_environments:
                raise PermissionError(
                    "failure trace collection is not allowed for this environment"
                )
        if selected == ["logs"] and self._config.logs.provider == "none":
            raise ValueError("failure log collection requires a configured log provider")
        if selected == ["traces"] and self._config.traces.provider == "none":
            raise ValueError("failure trace collection requires a configured trace provider")

    def _collect_case(
        self,
        command,
        selected,
        case,
        api_service,
        environment,
        evidence_sha,
        workspace_root,
        execution_root,
    ) -> FailureEvidenceCollection:
        log_query, log_sha, log_provider = self._log_input(
            command, selected, case, api_service, environment
        )
        trace_query, trace_sha, trace_provider = self._trace_input(
            command, selected, case, environment
        )
        input_payload = {
            "execution_evidence_sha256": evidence_sha,
            "sources": selected,
            "log_provider_structure_sha256": log_sha,
            "log_query": log_query.model_dump(mode="json") if log_query else None,
            "trace_provider_structure_sha256": trace_sha,
            "trace_query": trace_query.model_dump(mode="json") if trace_query else None,
        }
        input_sha = hashlib.sha256(
            json.dumps(input_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        collection_id = f"collection-{input_sha[:20]}"
        collection_root = execution_root / "triage" / "collections" / collection_id
        relative = collection_root.relative_to(workspace_root).as_posix()
        if collection_root.exists():
            return self._reuse(collection_root, relative, collection_id, input_sha, case, selected)
        staging = collection_root.parent / f".{collection_id}.staging"
        staging.parent.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        try:
            log_status, log_file_sha = self._collect_logs(
                staging, collection_id, evidence_sha, log_sha, log_query, log_provider
            )
            trace_status, trace_file_sha = self._collect_trace(
                staging, collection_id, evidence_sha, trace_sha, trace_query, trace_provider
            )
            manifest = {
                "schema_version": "agentic-qa.failure-evidence-collection-manifest.v1",
                "collection_id": collection_id,
                "input_sha256": input_sha,
                "sources": selected,
                "log_collection_status": log_status,
                "trace_collection_status": trace_status,
                "log_evidence_sha256": log_file_sha,
                "trace_evidence_sha256": trace_file_sha,
                "analysis_status": "not_started",
                "triage_status": "not_started",
            }
            create_only_json(staging / "collection-manifest.json", manifest)
            os.replace(staging, collection_root)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return FailureEvidenceCollection(
            collection_id=collection_id,
            case_id=case.case_id,
            dataset_id=case.dataset_id,
            sources=selected,
            log_collection_status=log_status,
            trace_collection_status=trace_status,
            collection_path=relative,
            log_evidence_path=(
                (collection_root / "log-evidence.json").relative_to(workspace_root).as_posix()
                if log_file_sha
                else None
            ),
            trace_evidence_path=(
                (collection_root / "trace-evidence.json").relative_to(workspace_root).as_posix()
                if trace_file_sha
                else None
            ),
        )

    def _log_input(self, command, selected, case, api_service, environment):
        if "logs" not in selected or self._config.logs.provider == "none":
            return None, None, None
        services = self._config.logs.api_service_scopes.get(api_service)
        if not services:
            if selected == ["logs"]:
                raise ValueError("execution service has no configured log service scope")
            return None, None, None
        logs = self._config.logs
        structure = {
            "provider": logs.provider,
            "query": logs.query.model_dump(mode="json"),
            "api_service": api_service,
            "services": services,
            "local_file": logs.local_file.model_dump(mode="json") if logs.local_file else None,
            "loki": logs.loki.model_dump(mode="json", exclude={"token"}) if logs.loki else None,
        }
        digest = self._structure_sha(structure)
        window = logs.query.default_window_seconds
        query = LogQueryRequest(
            workspace_id=command.workspace_id,
            execution_id=command.execution_id,
            case_id=case.case_id,
            dataset_id=case.dataset_id,
            environment=environment,
            api_service=api_service,
            services=services,
            started_at=case.started_at - timedelta(seconds=window),
            completed_at=case.completed_at + timedelta(seconds=window),
            max_entries=logs.query.default_max_entries,
            trace_id=case.correlation.trace_id,
            request_id=case.correlation.request_id,
            custom_ids=case.correlation.custom_ids,
        )
        provider: LogProvider = (
            LocalFileLogProvider(self._store.repo_root, logs)
            if logs.provider == "local-file"
            else LokiLogProvider(logs)
        )
        return query, digest, provider

    def _trace_input(self, command, selected, case, environment):
        if (
            "traces" not in selected
            or self._config.traces.provider == "none"
            or not case.correlation.trace_id
        ):
            return None, None, None
        traces = self._config.traces
        structure = {
            "provider": traces.provider,
            "query": traces.query.model_dump(mode="json"),
            "local_file": traces.local_file.model_dump(mode="json") if traces.local_file else None,
            "tempo": (
                traces.tempo.model_dump(mode="json", exclude={"token"}) if traces.tempo else None
            ),
        }
        query = TraceQueryRequest(
            workspace_id=command.workspace_id,
            execution_id=command.execution_id,
            case_id=case.case_id,
            dataset_id=case.dataset_id,
            environment=environment,
            trace_id=case.correlation.trace_id,
            started_at=case.started_at,
            completed_at=case.completed_at,
            max_spans=traces.query.default_max_spans,
        )
        if traces.provider != "local-file":
            return query, self._structure_sha(structure), None
        return (
            query,
            self._structure_sha(structure),
            LocalTraceProvider(self._store.repo_root, traces),
        )

    def _collect_logs(self, root, collection_id, evidence_sha, provider_sha, query, provider):
        if query is None or provider is None or provider_sha is None:
            return "unavailable", None
        try:
            result, redaction_count = provider.query(query)
        except (OSError, UnicodeError, ValueError) as exc:
            result = LogQueryResult(
                status="failed",
                diagnostics=[
                    ProviderDiagnostic(
                        code="LOG_PROVIDER_FAILED",
                        detail=f"log provider failed with {type(exc).__name__}",
                    )
                ],
            )
            redaction_count = 0
        payload = {
            "schema_version": "agentic-qa.log-evidence.v1",
            "collection_id": collection_id,
            "execution_id": query.execution_id,
            "case_id": query.case_id,
            "dataset_id": query.dataset_id,
            "execution_evidence_sha256": evidence_sha,
            "provider": self._config.logs.provider,
            "provider_structure_sha256": provider_sha,
            "query": query.model_dump(mode="json"),
            "status": result.status,
            "entries": [item.model_dump(mode="json") for item in result.entries],
            "diagnostics": [item.model_dump(mode="json") for item in result.diagnostics],
            "stats": LogEvidenceStats(
                entry_count=len(result.entries),
                service_counts={
                    service: sum(entry.service == service for entry in result.entries)
                    for service in sorted({entry.service for entry in result.entries})
                },
                level_counts={
                    level: sum(entry.level == level for entry in result.entries)
                    for level in sorted({entry.level for entry in result.entries})
                },
                redaction_count=redaction_count,
            ).model_dump(mode="json"),
        }
        digest = self._structure_sha(payload)
        bundle = LogEvidenceBundle.model_validate({**payload, "content_sha256": digest})
        path = root / "log-evidence.json"
        create_only_json(path, bundle.model_dump(mode="json"))
        return result.status, hashlib.sha256(path.read_bytes()).hexdigest()

    def _collect_trace(self, root, collection_id, evidence_sha, provider_sha, query, provider):
        if query is None or provider_sha is None:
            return "unavailable", None
        if provider is None:
            return "failed", None
        result = provider.get_trace(query)
        bundle = build_trace_evidence(
            collection_id=collection_id,
            execution_sha=evidence_sha,
            provider_sha=provider_sha,
            query=query,
            result=result,
            created_at=query.completed_at,
        )
        path = root / "trace-evidence.json"
        create_only_json(path, bundle.model_dump(mode="json"))
        return result.status, hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _reuse(root, relative, collection_id, input_sha, case, selected):
        manifest_path = root / "collection-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("input_sha256") != input_sha or manifest.get("sources") != selected:
            raise ValueError("existing failure evidence collection linkage is invalid")
        paths = {name: root / name for name in ("log-evidence.json", "trace-evidence.json")}
        for key, path in paths.items():
            expected = manifest.get(key.replace(".json", "_sha256").replace("-", "_"))
            if expected and (
                not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            ):
                raise ValueError("existing failure evidence collection hash is invalid")
        return FailureEvidenceCollection(
            collection_id=collection_id,
            case_id=case.case_id,
            dataset_id=case.dataset_id,
            sources=selected,
            log_collection_status=manifest.get("log_collection_status", "unavailable"),
            trace_collection_status=manifest.get("trace_collection_status", "unavailable"),
            collection_path=relative,
            log_evidence_path=(
                f"{relative}/log-evidence.json" if paths["log-evidence.json"].is_file() else None
            ),
            trace_evidence_path=(
                f"{relative}/trace-evidence.json"
                if paths["trace-evidence.json"].is_file()
                else None
            ),
        )

    @staticmethod
    def _structure_sha(payload) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
