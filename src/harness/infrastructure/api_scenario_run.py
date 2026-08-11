from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.domain.models import ExecuteApiCasesCommand, ExecutionProfile, RunApiScenarioCommand
from harness.domain.schemas.api_execution_reporting import (
    ApiExecutionPlan,
    ApiReportSummary,
    CleanupJournalCounts,
    CleanupJournalSummary,
    GenerateApiAllureReportCommand,
    GenerateApiAllureReportResult,
    ResumeApiCleanupCommand,
    ResumeApiCleanupResult,
)
from harness.domain.schemas.api_scenario import RunApiScenarioResult
from harness.domain.schemas.api_test_cases import (
    API_CASES_SCHEMA_VERSION,
    ApiTestCase,
    parse_api_case_variables,
    parse_api_cleanup_steps,
)
from harness.domain.schemas.execution_evidence import (
    EXECUTION_EVIDENCE_SCHEMA_VERSION,
    CaseExecutionEvidence,
    ExecutionEnvironment,
    ExecutionEvidence,
    ExecutionSummary,
)
from harness.infrastructure.api_automation import FilesystemApiAutomationService
from harness.infrastructure.api_cleanup_journal import EncryptedCleanupJournal
from harness.infrastructure.api_execution_plan import build_api_execution_plan
from harness.infrastructure.api_execution_reporting import (
    ApiExecutionEventWriter,
    build_report_summary,
    generate_allure_html,
    read_execution_events,
    write_allure_results,
)
from harness.infrastructure.persistence.common import (
    atomic_json,
    atomic_text,
    create_only_json,
    exclusive_file_lock,
)
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.tools.api_execution import (
    ApiAuthenticationError,
    api_cleanup_journal,
    api_execution_events,
)

UTC = timezone.utc
MANIFEST_SCHEMA = "agentic-qa.harness.api-execution-manifest.v2"


class FilesystemApiScenarioRunService:
    def __init__(
        self,
        store: FilesystemStore,
        automation: FilesystemApiAutomationService,
    ) -> None:
        self._store = store
        self._automation = automation

    def run(self, command: RunApiScenarioCommand) -> RunApiScenarioResult:
        workspace_root = self._store.require_workspace(command.workspace_id).resolve()
        executions_root = workspace_root / "executions"
        executions_root.mkdir(parents=True, exist_ok=True)
        execution_root = executions_root / command.execution_id
        lock_path = executions_root / ".locks" / f"{command.execution_id}.lock"
        with exclusive_file_lock(lock_path):
            self._reject_replay(execution_root)
            execution_root.mkdir()
            manifest_path = execution_root / "manifest.json"
            evidence_path = execution_root / "evidence.json"
            summary_path = execution_root / "summary.md"
            event_log_path = execution_root / "execution-events.jsonl"
            report_summary_path = execution_root / "report-summary.json"
            cleanup_summary_path = execution_root / "cleanup-summary.json"
            cleanup_journal_path = execution_root / ".cleanup-journal.enc"
            execution_plan_path = execution_root / "execution-plan.json"
            allure_results_path = execution_root / "allure-results"
            allure_report_path = execution_root / "allure-report"
            event_writer = ApiExecutionEventWriter(event_log_path, command.execution_id)
            manifest: dict[str, Any] = {
                "schema_version": MANIFEST_SCHEMA,
                "workspace_id": command.workspace_id,
                "execution_id": command.execution_id,
                "environment": command.environment,
                "status": "started",
                "started_at": datetime.now(tz=UTC).isoformat(),
                "source_cases_path": "published/api_test_draft/current.yml",
                "source_cases_sha256": None,
                "execution_plan_path": None,
                "execution_plan_sha256": None,
                "evidence_path": None,
                "evidence_sha256": None,
                "summary_path": None,
                "summary_sha256": None,
                "event_log_path": event_log_path.relative_to(workspace_root).as_posix(),
                "report_summary_path": None,
                "report_summary_sha256": None,
                "cleanup_summary_path": None,
                "cleanup_summary_sha256": None,
                "cleanup_journal_path": None,
                "cleanup_journal_sha256": None,
                "allure_results_path": None,
                "allure_results_sha256": None,
                "allure_report_path": None,
                "allure_report_sha256": None,
            }
            atomic_json(manifest_path, manifest)
            event_writer.emit(
                "execution.started",
                phase="execution",
                outcome="started",
                details={"environment": command.environment},
            )
            try:
                event_writer.emit("preflight.started", phase="preflight", outcome="started")
                self._automation.runtime_project(command.workspace_id, command.environment)
                profile = self._profile(command)
                execute_command = ExecuteApiCasesCommand(
                    workspace_id=command.workspace_id,
                    run_id=command.execution_id,
                    execution_profile=profile,
                )
                preflight = self._automation.preflight(execute_command)
                execute_command = execute_command.model_copy(
                    update={"source_cases_sha256": preflight.source_cases_sha256}
                )
                execution_plan = build_api_execution_plan(
                    workspace_id=command.workspace_id,
                    execution_id=command.execution_id,
                    service=preflight.service,
                    environment=command.environment,
                    source_cases_path=preflight.source_cases_path,
                    source_cases_sha256=preflight.source_cases_sha256,
                    structural_sha256=preflight.structural_sha256,
                    profile=profile,
                    authentication=preflight.authentication,
                    isolation=preflight.isolation,
                    operation_policies=preflight.operation_policies,
                    cases=preflight.cases,
                )
                create_only_json(execution_plan_path, execution_plan.model_dump(mode="json"))
                manifest["source_cases_path"] = preflight.source_cases_path
                manifest["source_cases_sha256"] = preflight.source_cases_sha256
                manifest["execution_plan_path"] = execution_plan_path.relative_to(
                    workspace_root
                ).as_posix()
                manifest["execution_plan_sha256"] = _sha256(execution_plan_path)
                atomic_json(manifest_path, manifest)
                event_writer.emit(
                    "preflight.finished",
                    phase="preflight",
                    outcome="passed",
                    details={
                        "source_cases_sha256": preflight.source_cases_sha256,
                        "execution_plan_sha256": execution_plan.plan_sha256,
                    },
                )
                has_cleanup = any(parse_api_cleanup_steps(case.cleanup) for case in preflight.cases)
                cleanup_journal = (
                    EncryptedCleanupJournal(
                        cleanup_journal_path,
                        key=self._automation.cleanup_journal_key(),
                        workspace_id=command.workspace_id,
                        execution_id=command.execution_id,
                        environment=command.environment,
                        source_cases_sha256=preflight.source_cases_sha256,
                        structural_sha256=preflight.structural_sha256,
                        execution_plan_sha256=execution_plan.plan_sha256,
                    )
                    if has_cleanup
                    else None
                )
            except Exception as exc:
                event_writer.emit(
                    "preflight.failed",
                    phase="preflight",
                    outcome="broken",
                    details={"error_kind": type(exc).__name__},
                )
                manifest.update(
                    {
                        "status": "preflight_failed",
                        "completed_at": datetime.now(tz=UTC).isoformat(),
                        "error_kind": type(exc).__name__,
                    }
                )
                atomic_json(manifest_path, manifest)
                raise

            try:
                journal_context = (
                    api_cleanup_journal(cleanup_journal)
                    if cleanup_journal is not None
                    else nullcontext()
                )
                with api_execution_events(_event_callback(event_writer)), journal_context:
                    try:
                        evidence = self._automation.execute_preflight(
                            execute_command,
                            preflight,
                        )
                    except ApiAuthenticationError:
                        evidence = _authentication_failure_evidence(
                            command,
                            preflight.cases,
                            preflight.source_cases_path,
                            profile,
                        )
                current_events = read_execution_events(event_log_path)
                cleanup_summary = (
                    cleanup_journal.summary()
                    if cleanup_journal is not None
                    else _cleanup_summary(evidence)
                )
                report_summary = build_report_summary(
                    evidence,
                    preflight.cases,
                    current_events,
                    cleanup_summary,
                )
                result_status = report_summary.result
                atomic_json(evidence_path, evidence.model_dump(mode="json"))
                atomic_json(report_summary_path, report_summary.model_dump(mode="json"))
                atomic_json(cleanup_summary_path, cleanup_summary.model_dump(mode="json"))
                atomic_text(
                    summary_path,
                    _render_summary(command, evidence, report_summary, cleanup_summary),
                )
                write_allure_results(
                    results_path=allure_results_path,
                    evidence=evidence,
                    summary=report_summary,
                    cases=preflight.cases,
                    service=preflight.service,
                    source_sha256=preflight.source_cases_sha256,
                    events=current_events,
                )
                report_result = generate_allure_html(
                    repo_root=self._store.repo_root,
                    workspace_id=command.workspace_id,
                    execution_id=command.execution_id,
                    results_path=allure_results_path,
                    report_path=allure_report_path,
                )
                event_writer.emit(
                    "report.finished",
                    phase="report",
                    outcome="passed" if report_result.status == "generated" else "pending",
                    details={"status": report_result.status},
                )
            except BaseException as exc:
                cleanup_state: CleanupJournalSummary | None = None
                if cleanup_journal is not None:
                    cleanup_state = cleanup_journal.summary()
                    atomic_json(
                        cleanup_summary_path,
                        cleanup_state.model_dump(mode="json"),
                    )
                event_writer.emit(
                    "execution.indeterminate",
                    phase="execution",
                    outcome="broken",
                    details={"error_kind": type(exc).__name__},
                )
                manifest.update(
                    {
                        "status": (
                            "cleanup_indeterminate"
                            if cleanup_state is not None and cleanup_state.status == "indeterminate"
                            else "indeterminate"
                        ),
                        "observed_at": datetime.now(tz=UTC).isoformat(),
                        "error_kind": type(exc).__name__,
                        "event_log_sha256": _sha256(event_log_path),
                    }
                )
                if cleanup_state is not None:
                    manifest.update(
                        {
                            "cleanup_summary_path": cleanup_summary_path.relative_to(
                                workspace_root
                            ).as_posix(),
                            "cleanup_summary_sha256": _sha256(cleanup_summary_path),
                            "cleanup_journal_path": cleanup_journal_path.relative_to(
                                workspace_root
                            ).as_posix(),
                            "cleanup_journal_sha256": _sha256(cleanup_journal_path),
                        }
                    )
                atomic_json(manifest_path, manifest)
                raise

            manifest.update(
                {
                    "status": "completed",
                    "result": result_status,
                    "completed_at": datetime.now(tz=UTC).isoformat(),
                    "evidence_path": evidence_path.relative_to(workspace_root).as_posix(),
                    "evidence_sha256": _sha256(evidence_path),
                    "summary_path": summary_path.relative_to(workspace_root).as_posix(),
                    "summary_sha256": _sha256(summary_path),
                    "event_log_sha256": _sha256(event_log_path),
                    "event_log_path": event_log_path.relative_to(workspace_root).as_posix(),
                    "report_summary_path": report_summary_path.relative_to(
                        workspace_root
                    ).as_posix(),
                    "report_summary_sha256": _sha256(report_summary_path),
                    "cleanup_summary_path": cleanup_summary_path.relative_to(
                        workspace_root
                    ).as_posix(),
                    "cleanup_summary_sha256": _sha256(cleanup_summary_path),
                    "cleanup_journal_path": (
                        cleanup_journal_path.relative_to(workspace_root).as_posix()
                        if cleanup_journal is not None
                        else None
                    ),
                    "cleanup_journal_sha256": (
                        _sha256(cleanup_journal_path) if cleanup_journal is not None else None
                    ),
                    "allure_results_path": allure_results_path.relative_to(
                        workspace_root
                    ).as_posix(),
                    "allure_results_sha256": _tree_sha256(allure_results_path),
                    "allure_report_path": (
                        report_result.allure_report_path
                        if report_result.status == "generated"
                        else None
                    ),
                    "allure_report_sha256": (
                        _tree_sha256(allure_report_path)
                        if report_result.status == "generated"
                        else None
                    ),
                    "allure_history_path": (
                        "allure-history.jsonl"
                        if (workspace_root / "allure-history.jsonl").is_file()
                        else None
                    ),
                    "report_status": report_result.status,
                    "summary": evidence.summary.model_dump(mode="json"),
                    "report_summary": report_summary.counts.model_dump(mode="json"),
                    "cleanup": cleanup_summary.model_dump(mode="json"),
                }
            )
            event_writer.emit(
                "execution.finished",
                phase="execution",
                outcome="passed" if result_status == "passed" else "failed",
                details={"result": result_status},
            )
            manifest["event_log_sha256"] = _sha256(event_log_path)
            atomic_json(manifest_path, manifest)
            return RunApiScenarioResult(
                workspace_id=command.workspace_id,
                execution_id=command.execution_id,
                environment=command.environment,
                status=result_status,
                source_cases_sha256=preflight.source_cases_sha256,
                manifest_path=manifest_path.relative_to(workspace_root).as_posix(),
                evidence_path=evidence_path.relative_to(workspace_root).as_posix(),
                summary_path=summary_path.relative_to(workspace_root).as_posix(),
                event_log_path=event_log_path.relative_to(workspace_root).as_posix(),
                report_summary_path=report_summary_path.relative_to(workspace_root).as_posix(),
                cleanup_summary_path=cleanup_summary_path.relative_to(workspace_root).as_posix(),
                allure_results_path=allure_results_path.relative_to(workspace_root).as_posix(),
                allure_report_path=report_result.allure_report_path,
                report_status=report_result.status,
                evidence=evidence,
            )

    def _profile(self, command: RunApiScenarioCommand) -> ExecutionProfile:
        return self._automation.execution_profile(command.workspace_id, command.environment)

    def generate_allure_report(
        self,
        command: GenerateApiAllureReportCommand,
    ) -> GenerateApiAllureReportResult:
        workspace_root = self._store.require_workspace(command.workspace_id).resolve()
        execution_root = workspace_root / "executions" / command.execution_id
        manifest_path = execution_root / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"API execution does not exist: {command.execution_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        results_path = execution_root / "allure-results"
        evidence_path = execution_root / "evidence.json"
        if not evidence_path.is_file():
            raise ValueError("execution has no Evidence from which to build Allure results")
        if not results_path.is_dir() or not (execution_root / "report-summary.json").is_file():
            cases, service, source_sha256 = self._automation.published_report_source(
                command.workspace_id
            )
            evidence = ExecutionEvidence.model_validate_json(
                evidence_path.read_text(encoding="utf-8")
            )
            report = build_report_summary(
                evidence,
                cases,
                read_execution_events(execution_root / "execution-events.jsonl"),
                _stored_cleanup_summary(execution_root, evidence),
            )
            atomic_json(
                execution_root / "report-summary.json",
                report.model_dump(mode="json"),
            )
            if not results_path.is_dir():
                write_allure_results(
                    results_path=results_path,
                    evidence=evidence,
                    summary=report,
                    cases=cases,
                    service=service,
                    source_sha256=str(manifest.get("source_cases_sha256") or source_sha256),
                    events=read_execution_events(execution_root / "execution-events.jsonl"),
                )
        result = generate_allure_html(
            repo_root=self._store.repo_root,
            workspace_id=command.workspace_id,
            execution_id=command.execution_id,
            results_path=results_path,
            report_path=execution_root / "allure-report",
        )
        manifest["report_status"] = result.status
        manifest["allure_results_path"] = results_path.relative_to(workspace_root).as_posix()
        manifest["allure_results_sha256"] = _tree_sha256(results_path)
        manifest["allure_report_path"] = result.allure_report_path
        manifest["allure_report_sha256"] = (
            _tree_sha256(execution_root / "allure-report") if result.status == "generated" else None
        )
        report_summary_path = execution_root / "report-summary.json"
        if report_summary_path.is_file():
            manifest["report_summary_path"] = report_summary_path.relative_to(
                workspace_root
            ).as_posix()
            manifest["report_summary_sha256"] = _sha256(report_summary_path)
        manifest["allure_history_path"] = (
            "allure-history.jsonl" if (workspace_root / "allure-history.jsonl").is_file() else None
        )
        atomic_json(manifest_path, manifest)
        return result

    def resume_cleanup(self, command: ResumeApiCleanupCommand) -> ResumeApiCleanupResult:
        workspace_root = self._store.require_workspace(command.workspace_id).resolve()
        lock_path = workspace_root / "executions" / ".locks" / f"{command.execution_id}.lock"
        with exclusive_file_lock(lock_path):
            return self._resume_cleanup_locked(command, workspace_root)

    def _resume_cleanup_locked(
        self,
        command: ResumeApiCleanupCommand,
        workspace_root: Path,
    ) -> ResumeApiCleanupResult:
        execution_root = workspace_root / "executions" / command.execution_id
        manifest_path = execution_root / "manifest.json"
        journal_path = execution_root / ".cleanup-journal.enc"
        if not manifest_path.is_file() or not journal_path.is_file():
            raise FileNotFoundError("execution does not contain a recoverable cleanup journal")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("environment") != command.environment:
            raise PermissionError("cleanup environment differs from the original execution")
        project = self._automation.runtime_project(command.workspace_id, command.environment)
        journal = EncryptedCleanupJournal.load(
            journal_path,
            key=self._automation.cleanup_journal_key(),
        )
        payload = journal.payload
        execution_plan_path = execution_root / "execution-plan.json"
        if not execution_plan_path.is_file():
            raise PermissionError(
                "immutable execution plan is missing; cleanup recovery is blocked"
            )
        execution_plan = ApiExecutionPlan.model_validate_json(
            execution_plan_path.read_text(encoding="utf-8")
        )
        if payload.get("execution_plan_sha256") != execution_plan.plan_sha256:
            raise PermissionError("execution plan changed; cleanup recovery is blocked")
        if manifest.get("execution_plan_sha256") != _sha256(execution_plan_path):
            raise PermissionError("execution plan hash changed; cleanup recovery is blocked")
        if payload.get("source_cases_sha256") != self._automation.published_sha256(
            command.workspace_id
        ):
            raise PermissionError("published API cases changed; cleanup recovery is blocked")
        if payload.get("structural_sha256") != project.structural_sha256:
            raise PermissionError("API safety policy changed; cleanup recovery is blocked")
        recovery_id = str(uuid.uuid4())
        writer = ApiExecutionEventWriter(
            execution_root / "execution-events.jsonl",
            command.execution_id,
        )
        writer.emit(
            "cleanup.recovery.started",
            phase="cleanup",
            outcome="started",
            details={"recovery_id": recovery_id},
        )
        initial = journal.summary()
        if initial.counts.armed or initial.counts.running:
            status = "indeterminate"
        elif initial.counts.failed:
            status = "failed"
        else:
            try:
                with api_execution_events(_event_callback(writer)):
                    for obligation in reversed(journal.pending()):
                        obligation_id = str(obligation["obligation_id"])
                        # Persist running before authentication or transport. A crash from
                        # this point is intentionally never auto-replayed.
                        journal.before(obligation_id)
                        outcome = self._automation.execute_cleanup_obligation(
                            workspace=command.workspace_id,
                            environment=command.environment,
                            execution_id=command.execution_id,
                            obligation=obligation,
                        )
                        journal.after(
                            obligation_id,
                            status=outcome.status,
                            request_sent=True,
                        )
                status = "complete" if journal.summary().status == "complete" else "failed"
            except BaseException as exc:
                status = "indeterminate"
                writer.emit(
                    "cleanup.recovery.indeterminate",
                    phase="cleanup",
                    outcome="broken",
                    details={
                        "recovery_id": recovery_id,
                        "error_kind": type(exc).__name__,
                    },
                )
        summary = journal.summary()
        cleanup_summary_path = execution_root / "cleanup-summary.json"
        atomic_json(cleanup_summary_path, summary.model_dump(mode="json"))
        writer.emit(
            "cleanup.recovery.finished",
            phase="cleanup",
            outcome="passed" if status == "complete" else "broken",
            details={"recovery_id": recovery_id, "status": status},
        )
        manifest["cleanup_recovery"] = {
            "recovery_id": recovery_id,
            "status": status,
            "completed_at": datetime.now(tz=UTC).isoformat(),
        }
        if status == "indeterminate":
            manifest["status"] = "cleanup_indeterminate"
        elif summary.status == "pending":
            manifest["status"] = "cleanup_pending"
        manifest["event_log_sha256"] = _sha256(execution_root / "execution-events.jsonl")
        manifest["cleanup_summary_sha256"] = _sha256(cleanup_summary_path)
        manifest["cleanup_journal_sha256"] = _sha256(journal_path)
        atomic_json(manifest_path, manifest)
        return ResumeApiCleanupResult(
            workspace_id=command.workspace_id,
            execution_id=command.execution_id,
            recovery_id=recovery_id,
            status=status,
            cleanup_summary_path=cleanup_summary_path.relative_to(workspace_root).as_posix(),
            summary=summary,
        )

    @staticmethod
    def _reject_replay(execution_root: Path) -> None:
        if not execution_root.exists():
            return
        manifest_path = execution_root / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                manifest = None
            if isinstance(manifest, dict) and manifest.get("status") == "started":
                manifest.update(
                    {
                        "status": "indeterminate",
                        "observed_at": datetime.now(tz=UTC).isoformat(),
                        "error_kind": "InterruptedExecution",
                    }
                )
                atomic_json(manifest_path, manifest)
        raise FileExistsError(
            f"execution ID already exists and will not be replayed: {execution_root.name}"
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _event_callback(writer: ApiExecutionEventWriter):
    def emit(event_type: str, payload: dict[str, Any]) -> None:
        status = str(payload.pop("status", ""))
        passed = payload.get("passed")
        if passed is False:
            outcome = "failed"
        elif event_type.endswith(".failed") or status in {"failed", "error", "blocked"}:
            outcome = "broken" if status != "failed" else "failed"
        elif event_type.endswith((".finished", ".received")):
            outcome = "passed"
        else:
            outcome = "started"
        phase = event_type.split(".", 1)[0]
        raw_case_id = payload.pop("case_id", None)
        case_id, dataset_id, inferred_cleanup_id = _event_scope(raw_case_id)
        writer.emit(
            event_type,
            phase="authentication" if phase == "authentication" else phase,
            outcome=outcome,
            case_id=case_id,
            dataset_id=payload.pop("dataset_id", None) or dataset_id,
            cleanup_id=payload.pop("cleanup_id", None) or inferred_cleanup_id,
            duration_ms=payload.pop("duration_ms", None),
            status_code=payload.pop("status_code", None),
            details=payload,
        )

    return emit


def _event_scope(case_id: object) -> tuple[str | None, str | None, str | None]:
    if not isinstance(case_id, str) or not case_id:
        return None, None, None
    main, separator, cleanup_id = case_id.partition("::cleanup::")
    base, dataset_separator, dataset_id = main.partition("::")
    return (
        base,
        dataset_id if dataset_separator else None,
        cleanup_id if separator else None,
    )


def _cleanup_summary(evidence: ExecutionEvidence) -> CleanupJournalSummary:
    cleanup = [item for item in evidence.cases if "::cleanup::" in item.case_id]
    completed = sum(item.status == "passed" for item in cleanup)
    failed = len(cleanup) - completed
    status = "not_required" if not cleanup else ("complete" if failed == 0 else "failed")
    return CleanupJournalSummary(
        execution_id=evidence.run_id,
        status=status,
        counts=CleanupJournalCounts(
            total=len(cleanup),
            pending=0,
            running=0,
            completed=completed,
            failed=failed,
        ),
        obligation_ids=[item.case_id for item in cleanup],
    )


def _stored_cleanup_summary(
    execution_root: Path,
    evidence: ExecutionEvidence,
) -> CleanupJournalSummary:
    path = execution_root / "cleanup-summary.json"
    if path.is_file():
        return CleanupJournalSummary.model_validate_json(path.read_text(encoding="utf-8"))
    return _cleanup_summary(evidence)


def _authentication_failure_evidence(
    command: RunApiScenarioCommand,
    cases: list[ApiTestCase],
    source_cases_path: str,
    profile: ExecutionProfile,
) -> ExecutionEvidence:
    started_at = datetime.now(tz=UTC)
    blocked: list[CaseExecutionEvidence] = []
    for case in cases:
        variables = parse_api_case_variables(case.variables)
        for dataset in variables.datasets or [None]:
            case_id = case.id if dataset is None else f"{case.id}::{dataset.id}"
            title = case.title if dataset is None else f"{case.title} [dataset:{dataset.id}]"
            now = datetime.now(tz=UTC)
            blocked.append(
                CaseExecutionEvidence(
                    case_id=case_id,
                    title=title,
                    method=str(case.request.method or ""),
                    path=str(case.request.path or ""),
                    status="blocked",
                    started_at=now,
                    completed_at=now,
                    duration_ms=0,
                    error="API authentication setup failed",
                )
            )
    return ExecutionEvidence(
        schema_version=EXECUTION_EVIDENCE_SCHEMA_VERSION,
        run_id=command.execution_id,
        source_cases_path=source_cases_path,
        source_cases_schema_version=API_CASES_SCHEMA_VERSION,
        started_at=started_at,
        completed_at=datetime.now(tz=UTC),
        environment=ExecutionEnvironment(
            name=profile.environment,
            base_url_env=profile.base_url_env,
            base_url_configured=True,
            allowed_methods=profile.allowed_http_methods,
            request_timeout_seconds=profile.request_timeout_seconds,
        ),
        summary=ExecutionSummary(
            total=len(blocked),
            executed=0,
            passed=0,
            failed=0,
            errors=0,
            blocked=len(blocked),
        ),
        cases=blocked,
    )


def _render_summary(
    command: RunApiScenarioCommand,
    evidence: ExecutionEvidence,
    report: ApiReportSummary,
    cleanup: CleanupJournalSummary,
) -> str:
    summary = report.counts
    lines = [
        "# API trial run summary",
        "",
        f"- Execution ID: `{command.execution_id}`",
        f"- Environment: `{command.environment}`",
        f"- Result: `{report.result}`",
        f"- Cleanup: `{cleanup.status}`",
        f"- Started: `{evidence.started_at.isoformat()}`",
        f"- Completed: `{evidence.completed_at.isoformat()}`",
        "",
        "## Counts",
        "",
        "| Total | Passed | Failed | Broken | Skipped |",
        "|---:|---:|---:|---:|---:|",
        f"| {summary.total} | {summary.passed} | {summary.failed} | "
        f"{summary.broken} | {summary.skipped} |",
        "",
        "## Cases",
        "",
        "| Case ID | Method | Status | HTTP | Duration (ms) |",
        "|---|---|---|---:|---:|",
    ]
    evidence_by_id = {item.case_id: item for item in evidence.cases}
    for case in report.cases:
        item = evidence_by_id.get(case.case_id)
        status_code = "" if item is None or item.status_code is None else str(item.status_code)
        method = "" if item is None else item.method
        duration = 0 if item is None else item.duration_ms
        lines.append(
            f"| `{_markdown(case.case_id)}` | `{_markdown(method)}` | "
            f"`{case.status}` | {status_code} | {duration} |"
        )
    lines.extend(
        [
            "",
            "Response bodies, response header values, runtime variables, credentials, and "
            "request data values are intentionally omitted.",
            "",
        ]
    )
    return "\n".join(lines)


def _markdown(value: str) -> str:
    return value.replace("`", "&#96;").replace("|", "&#124;").replace("\r", " ").replace("\n", " ")
