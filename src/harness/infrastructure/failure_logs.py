from __future__ import annotations

import hashlib
import json
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import requests

from harness.domain.schemas.api_execution_reporting import parse_api_execution_plan_json
from harness.domain.schemas.execution_evidence import load_execution_evidence
from harness.domain.schemas.local_config import AgenticQaLocalConfig, LocalLogsConfig
from harness.domain.schemas.log_evidence import (
    CollectFailureLogsCommand,
    CollectFailureLogsResult,
    FailureLogCollection,
    LogEvidenceBundle,
    LogEvidenceStats,
    LogQueryRequest,
    LogQueryResult,
    NormalizedLogEntry,
    ProviderDiagnostic,
)
from harness.domain.security import build_api_request_url, validate_api_response_url
from harness.infrastructure.api_execution_snapshot import ExecutionSourceSnapshotResolver
from harness.infrastructure.api_published_source import PublishedApiSourceResolver
from harness.infrastructure.failure_analysis import FilesystemFailureAnalysisService
from harness.infrastructure.log_sanitization import sanitize_log_text
from harness.infrastructure.persistence.common import create_only_json
from harness.infrastructure.persistence.filesystem import FilesystemStore

UTC = timezone.utc
ISO_TIMESTAMP = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2}))"
)
TEXT_LOG = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\S+)\s+"
    r"(?P<level>TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\s+(?P<message>.*)$",
    re.IGNORECASE,
)
PRODUCTION_LIKE = {"pro", "prod", "production", "live"}
REPARSE_POINT = 0x400
LOKI_VALUE = re.compile(r"^[0-9]{1,20}$")


class LogProvider(Protocol):
    def query(self, request: LogQueryRequest) -> tuple[LogQueryResult, int]: ...


class LocalFileLogProvider:
    def __init__(self, repo_root: Path, config: LocalLogsConfig) -> None:
        if config.local_file is None:
            raise ValueError("local-file provider configuration is missing")
        self._repo_root = repo_root.resolve()
        self._logs_root = (self._repo_root / "local-logs").resolve()
        self._config = config

    def query(self, request: LogQueryRequest) -> tuple[LogQueryResult, int]:
        entries: list[NormalizedLogEntry] = []
        diagnostics: list[ProviderDiagnostic] = []
        files: list[tuple[str, Path]] = []
        provider = self._config.local_file
        assert provider is not None
        for service in request.services:
            service_config = provider.services.get(service)
            if service_config is None:
                diagnostics.append(
                    ProviderDiagnostic(
                        code="LOG_SERVICE_NOT_CONFIGURED",
                        service=service,
                        detail="service has no local-file mapping",
                    )
                )
                continue
            for pattern in service_config.files:
                files.extend((service, item) for item in self._repo_root.glob(pattern))
        unique_files: dict[tuple[str, str], tuple[str, Path]] = {}
        for service, path in files:
            unique_files.setdefault((service, str(path.resolve())), (service, path))
        files = sorted(unique_files.values(), key=lambda item: (item[0], item[1].as_posix()))
        if len(files) > provider.max_files:
            raise ValueError("local log query exceeds configured file limit")
        total_bytes = 0
        redactions = 0
        for service, path in files:
            resolved = path.resolve()
            if not self._safe_regular_file(path, resolved):
                raise ValueError(f"local log path is not a safe regular file: {path.name}")
            size = resolved.stat().st_size
            if size > provider.max_file_bytes:
                raise ValueError(f"local log file exceeds configured byte limit: {path.name}")
            total_bytes += size
            if total_bytes > self._config.query.max_response_bytes:
                raise ValueError("local log query exceeds total response byte limit")
            text = resolved.read_text(encoding="utf-8-sig", errors="replace")
            for line_number, line in enumerate(text.splitlines(), 1):
                raw = self._parse_line(line, service)
                if raw is None or not self._matches(raw, request):
                    continue
                preserve = {
                    value
                    for value in (
                        request.trace_id,
                        request.request_id,
                        *request.custom_ids.values(),
                    )
                    if value
                }
                message, count = sanitize_log_text(raw["message"], preserve=preserve)
                exception_type, exception_redactions = sanitize_log_text(
                    raw.get("exception_type") or "", preserve=preserve
                )
                redactions += count
                redactions += exception_redactions
                entries.append(
                    NormalizedLogEntry(
                        entry_id=f"LOG-{len(entries) + 1:06d}",
                        timestamp=raw["timestamp"],
                        service=service,
                        level=raw["level"],
                        message=message,
                        trace_id=(
                            request.trace_id
                            if request.trace_id and raw.get("trace_id") == request.trace_id
                            else None
                        ),
                        span_id=raw.get("span_id"),
                        request_id=(
                            request.request_id
                            if request.request_id and raw.get("request_id") == request.request_id
                            else None
                        ),
                        exception_type=exception_type or None,
                        source_ref=f"{resolved.relative_to(self._repo_root).as_posix()}:{line_number}",
                    )
                )
                if len(entries) >= request.max_entries:
                    break
            if len(entries) >= request.max_entries:
                break
        status = "success" if entries else "empty"
        return (
            LogQueryResult(
                status=status,
                entries=entries,
                diagnostics=diagnostics,
                files_considered=len(files),
                bytes_read=total_bytes,
            ),
            redactions,
        )

    def _safe_regular_file(self, path: Path, resolved: Path) -> bool:
        if not path.exists() or not path.is_file() or self._logs_root not in resolved.parents:
            return False
        current = path
        while current != self._repo_root:
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or bool(
                getattr(info, "st_file_attributes", 0) & REPARSE_POINT
            ):
                return False
            current = current.parent
        return current == self._repo_root

    @staticmethod
    def _parse_line(line: str, service: str) -> dict[str, Any] | None:
        if not line.strip():
            return None
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            match = TEXT_LOG.match(line)
            if match:
                return {
                    "timestamp": _timestamp(match.group("timestamp")),
                    "level": match.group("level").upper(),
                    "message": match.group("message"),
                }
            return {"timestamp": None, "level": "UNKNOWN", "message": line}
        if not isinstance(payload, dict):
            return None
        timestamp = next(
            (
                payload.get(name)
                for name in ("timestamp", "time", "@timestamp", "ts")
                if payload.get(name)
            ),
            None,
        )
        message = next(
            (
                payload.get(name)
                for name in ("message", "msg", "log")
                if payload.get(name) is not None
            ),
            "",
        )
        exception = payload.get("exception")
        exception_type = payload.get("exception_type") or payload.get("exceptionType")
        if isinstance(exception, dict):
            exception_type = exception_type or exception.get("type") or exception.get("class")
            exception = exception.get("message") or json.dumps(exception, ensure_ascii=False)
        if exception:
            message = f"{message}\n{exception}" if message else str(exception)
        return {
            "timestamp": _timestamp(timestamp),
            "level": str(payload.get("level") or payload.get("severity") or "UNKNOWN").upper(),
            "message": str(message),
            "trace_id": _first(payload, "trace_id", "traceId", "trace", "x-trace-id"),
            "span_id": _first(payload, "span_id", "spanId", "span"),
            "request_id": _first(payload, "request_id", "requestId", "x-request-id"),
            "exception_type": str(exception_type) if exception_type else None,
            "service": service,
        }

    @staticmethod
    def _matches(entry: dict[str, Any], request: LogQueryRequest) -> bool:
        identifiers = {
            value
            for value in (request.trace_id, request.request_id, *request.custom_ids.values())
            if value
        }
        if identifiers:
            haystack = " ".join(
                str(value)
                for value in (entry.get("trace_id"), entry.get("request_id"), entry["message"])
                if value
            )
            return any(item in haystack for item in identifiers)
        timestamp = entry.get("timestamp")
        return timestamp is not None and request.started_at <= timestamp <= request.completed_at


class LokiLogProvider:
    def __init__(
        self,
        config: LocalLogsConfig,
        *,
        request_func: Any = requests.get,
    ) -> None:
        if config.loki is None:
            raise ValueError("loki provider configuration is missing")
        self._logs = config
        self._config = config.loki
        self._request = request_func

    def query(self, request: LogQueryRequest) -> tuple[LogQueryResult, int]:
        if request.completed_at - request.started_at > timedelta(
            seconds=self._logs.query.max_window_seconds
        ):
            raise ValueError("Loki query exceeds configured time window")
        url = build_api_request_url(self._config.base_url, "/loki/api/v1/query_range")
        query = self._build_logql(request)
        try:
            response = self._request(
                url,
                params={
                    "query": query,
                    "start": str(int(request.started_at.timestamp() * 1_000_000_000)),
                    "end": str(int(request.completed_at.timestamp() * 1_000_000_000)),
                    "limit": str(request.max_entries),
                    "direction": "forward",
                },
                headers={"Authorization": f"Bearer {self._config.token}"},
                timeout=self._config.timeout_seconds,
                allow_redirects=False,
                stream=True,
            )
            validate_api_response_url(getattr(response, "url", None), requested_url=url)
            status_code = int(response.status_code)
            if 300 <= status_code < 400:
                return self._failed("LOKI_REDIRECT_REJECTED", "Loki redirect was rejected")
            if status_code != 200:
                return self._failed("LOKI_HTTP_ERROR", f"Loki returned HTTP status {status_code}")
            body = self._bounded_body(response)
            payload = json.loads(body.decode("utf-8"))
        except (
            requests.RequestException,
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            return self._failed("LOKI_QUERY_FAILED", f"Loki query failed with {type(exc).__name__}")
        if not isinstance(payload, dict) or payload.get("status") != "success":
            return self._failed("LOKI_RESPONSE_INVALID", "Loki response is not successful")
        data = payload.get("data")
        streams = data.get("result") if isinstance(data, dict) else None
        if not isinstance(streams, list):
            return self._failed("LOKI_RESPONSE_INVALID", "Loki streams are missing")
        return self._normalize_streams(streams, request, len(body))

    def _bounded_body(self, response: Any) -> bytes:
        limit = self._logs.query.max_response_bytes
        header = response.headers.get("Content-Length") if hasattr(response, "headers") else None
        if header:
            try:
                if int(header) > limit:
                    raise ValueError("Loki response exceeds configured byte limit")
            except ValueError as exc:
                raise OSError("invalid or excessive Loki Content-Length") from exc
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=65_536):
            if not chunk:
                continue
            size += len(chunk)
            if size > limit:
                raise OSError("Loki response exceeds configured byte limit")
            chunks.append(chunk)
        return b"".join(chunks)

    def _normalize_streams(
        self,
        streams: list[Any],
        request: LogQueryRequest,
        bytes_read: int,
    ) -> tuple[LogQueryResult, int]:
        entries: list[NormalizedLogEntry] = []
        diagnostics: list[ProviderDiagnostic] = []
        redactions = 0
        allowed = set(request.services)
        preserve = {
            value
            for value in (request.trace_id, request.request_id, *request.custom_ids.values())
            if value
        }
        for stream_index, item in enumerate(streams):
            if not isinstance(item, dict):
                continue
            labels = item.get("stream")
            values = item.get("values")
            service = labels.get(self._config.service_label) if isinstance(labels, dict) else None
            stream_environment = (
                labels.get(self._config.environment_label) if isinstance(labels, dict) else None
            )
            if service not in allowed or stream_environment != request.environment:
                diagnostics.append(
                    ProviderDiagnostic(
                        code="LOKI_STREAM_OUT_OF_SCOPE",
                        detail="Loki returned a stream outside the configured scope",
                    )
                )
                continue
            if not isinstance(values, list):
                continue
            for value_index, value in enumerate(values):
                if (
                    not isinstance(value, list)
                    or len(value) != 2
                    or not isinstance(value[0], str)
                    or not LOKI_VALUE.fullmatch(value[0])
                    or not isinstance(value[1], str)
                ):
                    continue
                timestamp = datetime.fromtimestamp(int(value[0]) / 1_000_000_000, tz=UTC)
                raw = LocalFileLogProvider._parse_line(value[1], service)
                if raw is None:
                    continue
                raw["timestamp"] = raw.get("timestamp") or timestamp
                if not LocalFileLogProvider._matches(raw, request):
                    continue
                message, count = sanitize_log_text(raw["message"], preserve=preserve)
                exception, exception_count = sanitize_log_text(
                    raw.get("exception_type") or "", preserve=preserve
                )
                redactions += count + exception_count
                entries.append(
                    NormalizedLogEntry(
                        entry_id=f"LOG-{len(entries) + 1:06d}",
                        timestamp=raw["timestamp"],
                        service=service,
                        level=raw["level"],
                        message=message,
                        trace_id=(
                            request.trace_id
                            if request.trace_id and raw.get("trace_id") == request.trace_id
                            else None
                        ),
                        span_id=raw.get("span_id"),
                        request_id=(
                            request.request_id
                            if request.request_id and raw.get("request_id") == request.request_id
                            else None
                        ),
                        exception_type=exception or None,
                        source_ref=f"loki:{service}:{stream_index}:{value_index}",
                    )
                )
                if len(entries) >= request.max_entries:
                    break
            if len(entries) >= request.max_entries:
                break
        return (
            LogQueryResult(
                status="success" if entries else "empty",
                entries=entries,
                diagnostics=diagnostics,
                bytes_read=bytes_read,
            ),
            redactions,
        )

    def _build_logql(self, request: LogQueryRequest) -> str:
        services = "|".join(re.escape(item) for item in sorted(set(request.services)))
        selectors = [
            f'{self._config.environment_label}="{_logql_string(request.environment)}"',
            f'{self._config.service_label}=~"{_logql_string(services)}"',
        ]
        query = "{" + ",".join(selectors) + "}"
        identifiers = sorted(
            {
                item
                for item in (request.trace_id, request.request_id, *request.custom_ids.values())
                if item
            }
        )
        if identifiers:
            correlation = "|".join(re.escape(item) for item in identifiers)
            query += f' |~ "{_logql_string(correlation)}"'
        return query

    @staticmethod
    def _failed(code: str, detail: str) -> tuple[LogQueryResult, int]:
        return (
            LogQueryResult(
                status="failed",
                diagnostics=[ProviderDiagnostic(code=code, detail=detail)],
            ),
            0,
        )


class FilesystemFailureLogService:
    def __init__(
        self,
        store: FilesystemStore,
        config: AgenticQaLocalConfig,
    ) -> None:
        self._store = store
        self._config = config
        self._snapshots = ExecutionSourceSnapshotResolver(store, PublishedApiSourceResolver(store))
        self._analysis = FilesystemFailureAnalysisService(store)

    def analyze(self, command):
        return self._analysis.analyze(command)

    def collect(self, command: CollectFailureLogsCommand) -> CollectFailureLogsResult:
        snapshot = self._snapshots.resolve(command.workspace_id, command.execution_id)
        logs = self._config.logs
        if logs.provider not in {"local-file", "loki"}:
            raise ValueError("failure log collection requires a configured log provider")
        environment = snapshot.environment.casefold()
        if environment in PRODUCTION_LIKE or environment not in logs.allowed_environments:
            raise PermissionError("failure log collection is not allowed for this environment")
        services = logs.api_service_scopes.get(snapshot.service)
        if not services:
            raise ValueError("execution service has no configured log service scope")
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
        ]
        if command.case_id is not None:
            eligible = [item for item in eligible if item.case_id == command.case_id]
        if not eligible:
            raise ValueError("no eligible failed or dispatched-error case instances")
        provider_structure = {
            "provider": logs.provider,
            "query": logs.query.model_dump(mode="json"),
            "api_service": snapshot.service,
            "services": services,
            "local_file": logs.local_file.model_dump(mode="json") if logs.local_file else None,
            "loki": (logs.loki.model_dump(mode="json", exclude={"token"}) if logs.loki else None),
        }
        provider_sha = hashlib.sha256(
            json.dumps(provider_structure, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        provider: LogProvider
        if logs.provider == "local-file":
            provider = LocalFileLogProvider(self._store.repo_root, logs)
        else:
            provider = LokiLogProvider(logs)
        collections = [
            self._collect_case(
                command,
                case,
                snapshot.service,
                snapshot.environment,
                services,
                evidence_sha,
                provider_sha,
                provider,
                workspace_root,
                execution_root,
            )
            for case in eligible
        ]
        return CollectFailureLogsResult(
            workspace_id=command.workspace_id,
            execution_id=command.execution_id,
            collections=collections,
            succeeded=sum(item.log_collection_status == "success" for item in collections),
            empty=sum(item.log_collection_status == "empty" for item in collections),
            failed=sum(item.log_collection_status == "failed" for item in collections),
        )

    def _collect_case(
        self,
        command: CollectFailureLogsCommand,
        case: Any,
        api_service: str,
        environment: str,
        services: list[str],
        evidence_sha: str,
        provider_sha: str,
        provider: LogProvider,
        workspace_root: Path,
        execution_root: Path,
    ) -> FailureLogCollection:
        window = self._config.logs.query.default_window_seconds
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
            max_entries=self._config.logs.query.default_max_entries,
            trace_id=case.correlation.trace_id,
            request_id=case.correlation.request_id,
            custom_ids=case.correlation.custom_ids,
        )
        input_payload = {
            "execution_evidence_sha256": evidence_sha,
            "provider_structure_sha256": provider_sha,
            "query": query.model_dump(mode="json"),
        }
        input_sha = hashlib.sha256(
            json.dumps(input_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        collection_id = f"collection-{input_sha[:20]}"
        collection_root = execution_root / "triage" / "collections" / collection_id
        relative = collection_root.relative_to(workspace_root).as_posix()
        evidence_file = collection_root / "log-evidence.json"
        if collection_root.exists():
            manifest_file = collection_root / "collection-manifest.json"
            payload = json.loads(evidence_file.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            bundle = LogEvidenceBundle.model_validate(payload)
            if (
                manifest.get("input_sha256") != input_sha
                or manifest.get("log_evidence_sha256")
                != hashlib.sha256(evidence_file.read_bytes()).hexdigest()
                or bundle.execution_evidence_sha256 != evidence_sha
                or bundle.provider_structure_sha256 != provider_sha
                or bundle.query != query
            ):
                raise ValueError("existing failure log collection linkage is invalid")
            return FailureLogCollection(
                collection_id=collection_id,
                case_id=case.case_id,
                dataset_id=case.dataset_id,
                log_collection_status=bundle.status,
                collection_path=relative,
                log_evidence_path=evidence_file.relative_to(workspace_root).as_posix(),
            )
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
        collection_root.mkdir(parents=True, exist_ok=False)
        create_only_json(collection_root / "log-query.json", query.model_dump(mode="json"))
        service_counts = {
            service: sum(item.service == service for item in result.entries)
            for service in sorted({item.service for item in result.entries})
        }
        level_counts = {
            level: sum(item.level == level for item in result.entries)
            for level in sorted({item.level for item in result.entries})
        }
        bundle_payload = {
            "schema_version": "agentic-qa.log-evidence.v1",
            "collection_id": collection_id,
            "execution_id": command.execution_id,
            "case_id": case.case_id,
            "dataset_id": case.dataset_id,
            "execution_evidence_sha256": evidence_sha,
            "provider": self._config.logs.provider,
            "provider_structure_sha256": provider_sha,
            "query": query.model_dump(mode="json"),
            "status": result.status,
            "entries": [item.model_dump(mode="json") for item in result.entries],
            "diagnostics": [item.model_dump(mode="json") for item in result.diagnostics],
            "stats": LogEvidenceStats(
                entry_count=len(result.entries),
                service_counts=service_counts,
                level_counts=level_counts,
                redaction_count=redaction_count,
            ).model_dump(mode="json"),
        }
        content_sha = hashlib.sha256(
            json.dumps(bundle_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        bundle = LogEvidenceBundle.model_validate({**bundle_payload, "content_sha256": content_sha})
        create_only_json(evidence_file, bundle.model_dump(mode="json"))
        create_only_json(
            collection_root / "collection-manifest.json",
            {
                "schema_version": "agentic-qa.failure-log-collection-manifest.v1",
                "collection_id": collection_id,
                "input_sha256": input_sha,
                "log_collection_status": result.status,
                "log_evidence_sha256": hashlib.sha256(evidence_file.read_bytes()).hexdigest(),
                "analysis_status": "not_started",
                "triage_status": "not_started",
            },
        )
        return FailureLogCollection(
            collection_id=collection_id,
            case_id=case.case_id,
            dataset_id=case.dataset_id,
            log_collection_status=result.status,
            collection_path=relative,
            log_evidence_path=evidence_file.relative_to(workspace_root).as_posix(),
        )


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, int | float):
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=UTC)
    if not isinstance(value, str):
        return None
    match = ISO_TIMESTAMP.search(value)
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group("timestamp").replace("Z", "+00:00"))
    except ValueError:
        return None


def _first(payload: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = payload.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _logql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
