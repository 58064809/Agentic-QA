from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.domain.models import ExecuteApiCasesCommand, ExecutionProfile, RunApiScenarioCommand
from harness.domain.schemas.api_execution_reporting import (
    ApiReportSummary,
    CleanupJournalCounts,
    CleanupJournalSummary,
    GenerateApiAllureReportCommand,
    GenerateApiAllureReportResult,
    ResumeApiCleanupCommand,
    ResumeApiCleanupResult,
    parse_api_execution_plan_json,
)
from harness.domain.schemas.api_scenario import RunApiScenarioResult
from harness.domain.schemas.api_test_cases import (
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
from harness.infrastructure.api_execution_snapshot import (
    ExecutionSourceLinkageError,
    ExecutionSourceSnapshot,
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
MANIFEST_SCHEMA = "agentic-qa.harness.api-execution-manifest.v3"


@dataclass(frozen=True)
class _ReportingPhaseOutcome:
    result: GenerateApiAllureReportResult
    event_log_path: str | None
    summary_path: str | None
    report_summary_path: str | None
    allure_results_path: str | None
    allure_report_path: str | None


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
            event_log_path = execution_root / "execution-events.jsonl"
            cleanup_summary_path = execution_root / "cleanup-summary.json"
            cleanup_journal_path = execution_root / ".cleanup-journal.enc"
            execution_plan_path = execution_root / "execution-plan.json"
            event_writer = ApiExecutionEventWriter(event_log_path, command.execution_id)
            manifest: dict[str, Any] = {
                "schema_version": MANIFEST_SCHEMA,
                "workspace_id": command.workspace_id,
                "execution_id": command.execution_id,
                "environment": command.environment,
                "status": "started",
                "execution_status": "running",
                "test_result": "not_run",
                "cleanup_status": "not_started",
                "report_status": "not_started",
                "started_at": datetime.now(tz=UTC).isoformat(),
                "source_cases_path": "published/api_test_draft/current.yml",
                "source_cases_sha256": None,
                "source_publication_id": None,
                "source_history_path": None,
                "policy_sha256": None,
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
                    source_publication_id=preflight.source_publication_id,
                    source_history_path=preflight.source_history_path,
                    structural_sha256=preflight.structural_sha256,
                    policy_sha256=preflight.policy_sha256,
                    profile=profile,
                    authentication=preflight.authentication,
                    isolation=preflight.isolation,
                    operation_policies=preflight.operation_policies,
                    cases=preflight.cases,
                )
                create_only_json(execution_plan_path, execution_plan.model_dump(mode="json"))
                manifest["source_cases_path"] = preflight.source_cases_path
                manifest["source_cases_sha256"] = preflight.source_cases_sha256
                manifest["source_publication_id"] = preflight.source_publication_id
                manifest["source_history_path"] = preflight.source_history_path
                manifest["policy_sha256"] = preflight.policy_sha256
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
                        source_publication_id=preflight.source_publication_id,
                        source_history_path=preflight.source_history_path,
                        structural_sha256=preflight.structural_sha256,
                        policy_sha256=preflight.policy_sha256,
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
                        "execution_status": "preflight_failed",
                        "test_result": "not_run",
                        "cleanup_status": "not_started",
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
                            preflight.source_cases_schema_version,
                            profile,
                        )
                cleanup_summary = (
                    cleanup_journal.summary()
                    if cleanup_journal is not None
                    else _cleanup_summary(evidence)
                )
                report_summary = build_report_summary(
                    evidence,
                    preflight.cases,
                    read_execution_events(event_log_path),
                    cleanup_summary,
                )
                if report_summary.counts.broken:
                    result_status = "broken"
                elif report_summary.counts.failed:
                    result_status = "failed"
                elif (
                    report_summary.counts.total
                    and report_summary.counts.skipped == report_summary.counts.total
                ):
                    result_status = "skipped"
                else:
                    result_status = "passed"
                atomic_json(evidence_path, evidence.model_dump(mode="json"))
                atomic_json(cleanup_summary_path, cleanup_summary.model_dump(mode="json"))
                event_writer.emit(
                    "execution.finished",
                    phase="execution",
                    outcome=result_status,
                    details={"result": result_status},
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
                        "execution_status": "indeterminate",
                        "test_result": "broken",
                        "cleanup_status": (
                            cleanup_state.status if cleanup_state is not None else "not_started"
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
                    "execution_status": "completed",
                    "test_result": result_status,
                    "cleanup_status": cleanup_summary.status,
                    "report_status": "not_started",
                    "completed_at": datetime.now(tz=UTC).isoformat(),
                    "evidence_path": evidence_path.relative_to(workspace_root).as_posix(),
                    "evidence_sha256": _sha256(evidence_path),
                    "event_log_sha256": _sha256(event_log_path),
                    "event_log_path": event_log_path.relative_to(workspace_root).as_posix(),
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
                    "summary": evidence.summary.model_dump(mode="json"),
                    "cleanup": cleanup_summary.model_dump(mode="json"),
                }
            )
            manifest["event_log_sha256"] = _sha256(event_log_path)
            atomic_json(manifest_path, manifest)

            reporting = self._run_reporting_phase(
                workspace_root=workspace_root,
                execution_root=execution_root,
                manifest=manifest,
                evidence=evidence,
                cleanup_summary=cleanup_summary,
                report_summary=report_summary,
            )
            report_result = reporting.result
            return RunApiScenarioResult(
                workspace_id=command.workspace_id,
                execution_id=command.execution_id,
                environment=command.environment,
                status=result_status,
                execution_status="completed",
                test_result=result_status,
                cleanup_status=cleanup_summary.status,
                source_cases_sha256=preflight.source_cases_sha256,
                manifest_path=manifest_path.relative_to(workspace_root).as_posix(),
                evidence_path=evidence_path.relative_to(workspace_root).as_posix(),
                summary_path=reporting.summary_path,
                event_log_path=reporting.event_log_path,
                report_summary_path=reporting.report_summary_path,
                cleanup_summary_path=cleanup_summary_path.relative_to(workspace_root).as_posix(),
                allure_results_path=reporting.allure_results_path,
                allure_report_path=reporting.allure_report_path,
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
        evidence_path = execution_root / "evidence.json"
        if not evidence_path.is_file():
            raise ValueError("execution has no Evidence from which to build Allure results")
        cases, snapshot = self._automation.published_report_source(
            command.workspace_id, command.execution_id
        )
        evidence = ExecutionEvidence.model_validate_json(evidence_path.read_text(encoding="utf-8"))
        _validate_report_evidence(evidence, snapshot)
        cleanup_summary = _stored_cleanup_summary(execution_root, evidence)
        report_summary = build_report_summary(
            evidence,
            cases,
            read_execution_events(execution_root / "execution-events.jsonl"),
            cleanup_summary,
        )
        return self._run_reporting_phase(
            workspace_root=workspace_root,
            execution_root=execution_root,
            manifest=manifest,
            evidence=evidence,
            cleanup_summary=cleanup_summary,
            report_summary=report_summary,
            cases=cases,
            snapshot=snapshot,
        ).result

    def _run_reporting_phase(
        self,
        *,
        workspace_root: Path,
        execution_root: Path,
        manifest: dict[str, Any],
        evidence: ExecutionEvidence,
        cleanup_summary: CleanupJournalSummary,
        report_summary: ApiReportSummary,
        cases: list[ApiTestCase] | None = None,
        snapshot: ExecutionSourceSnapshot | None = None,
    ) -> _ReportingPhaseOutcome:
        workspace_id = str(manifest["workspace_id"])
        execution_id = str(manifest["execution_id"])
        manifest_path = execution_root / "manifest.json"
        event_log_path = execution_root / "execution-events.jsonl"
        summary_path = execution_root / "summary.md"
        report_summary_path = execution_root / "report-summary.json"
        results_path = execution_root / "allure-results"
        report_path = execution_root / "allure-report"
        writer: ApiExecutionEventWriter | None = None
        try:
            writer = ApiExecutionEventWriter(event_log_path, execution_id)
            writer.emit("report.started", phase="report", outcome="started")
            if cases is None or snapshot is None:
                cases, snapshot = self._automation.published_report_source(
                    workspace_id, execution_id
                )
            _validate_report_evidence(evidence, snapshot)
            current_events = read_execution_events(event_log_path)
            atomic_json(report_summary_path, report_summary.model_dump(mode="json"))
            atomic_text(
                summary_path,
                _render_summary(
                    execution_id,
                    snapshot.environment,
                    evidence,
                    report_summary,
                    cleanup_summary,
                ),
            )
            if not results_path.is_dir():
                write_allure_results(
                    results_path=results_path,
                    evidence=evidence,
                    summary=report_summary,
                    cases=cases,
                    service=snapshot.service,
                    source_sha256=snapshot.source_cases_sha256,
                    events=current_events,
                )
            result = generate_allure_html(
                repo_root=self._store.repo_root,
                workspace_id=workspace_id,
                execution_id=execution_id,
                results_path=results_path,
                report_path=report_path,
            )
        except Exception as exc:
            result = _failed_report_result(
                workspace_root,
                workspace_id,
                execution_id,
                results_path,
                exc,
            )

        try:
            _update_report_manifest(
                manifest,
                workspace_root=workspace_root,
                execution_root=execution_root,
                report_summary=report_summary,
                result=result,
            )
            atomic_json(manifest_path, manifest)
        except Exception as exc:
            result = _failed_report_result(
                workspace_root,
                workspace_id,
                execution_id,
                results_path,
                exc,
            )
            manifest["report_status"] = "failed"
            manifest["report_error_kind"] = type(exc).__name__

        report_event_error = _safe_report_event(writer, result)
        if report_event_error is not None:
            result = GenerateApiAllureReportResult(
                workspace_id=workspace_id,
                execution_id=execution_id,
                status="failed",
                allure_results_path=_existing_relative(
                    results_path, workspace_root, directory=True
                ),
                message="report event persistence failed without changing execution truth",
                error_kind=report_event_error,
            )
            manifest["report_status"] = "failed"
            manifest["report_error_kind"] = result.error_kind

        try:
            _update_report_manifest(
                manifest,
                workspace_root=workspace_root,
                execution_root=execution_root,
                report_summary=report_summary,
                result=result,
            )
            atomic_json(manifest_path, manifest)
        except Exception as exc:
            result = _failed_report_result(
                workspace_root,
                workspace_id,
                execution_id,
                results_path,
                exc,
            )
        return _reporting_outcome(
            result,
            workspace_root=workspace_root,
            execution_root=execution_root,
        )

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
        execution_plan = parse_api_execution_plan_json(
            execution_plan_path.read_text(encoding="utf-8")
        )
        if payload.get("execution_plan_sha256") != execution_plan.plan_sha256:
            raise PermissionError("execution plan changed; cleanup recovery is blocked")
        if manifest.get("execution_plan_sha256") != _sha256(execution_plan_path):
            raise PermissionError("execution plan hash changed; cleanup recovery is blocked")
        source_cases_sha256 = str(payload.get("source_cases_sha256") or "")
        if source_cases_sha256 != execution_plan.source_cases_sha256:
            raise PermissionError("cleanup journal source differs from execution plan")
        source_publication_id = payload.get("source_publication_id") or getattr(
            execution_plan, "source_publication_id", None
        )
        source_history_path = payload.get("source_history_path") or getattr(
            execution_plan, "source_history_path", None
        )
        self._automation.validate_historical_source(
            command.workspace_id,
            source_publication_id=source_publication_id,
            source_history_path=source_history_path,
            source_cases_sha256=source_cases_sha256,
        )
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
        project = self._automation.recovery_runtime_project(
            command.workspace_id, command.environment
        )
        original_policy_sha256 = payload.get("policy_sha256") or getattr(
            execution_plan, "policy_sha256", None
        )
        current_policy_sha256 = project.policy_sha256
        legacy_policy_changed = (
            original_policy_sha256 is None
            and payload.get("structural_sha256") != project.structural_sha256
        )
        if legacy_policy_changed or (
            original_policy_sha256 is not None and original_policy_sha256 != current_policy_sha256
        ):
            return self._manual_reapproval_required(
                command=command,
                workspace_root=workspace_root,
                execution_root=execution_root,
                manifest_path=manifest_path,
                manifest=manifest,
                journal=journal,
                writer=writer,
                recovery_id=recovery_id,
                original_policy_sha256=str(
                    original_policy_sha256 or payload.get("structural_sha256") or ""
                ),
                current_policy_sha256=current_policy_sha256,
            )
        with api_execution_events(_event_callback(writer)):
            for obligation in reversed(journal.pending()):
                obligation_id = str(obligation["obligation_id"])
                # Persist running before authentication or transport. A crash from
                # this point is intentionally never auto-replayed.
                journal.before(obligation_id)
                try:
                    outcome = self._automation.execute_cleanup_obligation(
                        workspace=command.workspace_id,
                        environment=command.environment,
                        execution_id=command.execution_id,
                        obligation=obligation,
                        project=project,
                    )
                except Exception as exc:
                    writer.emit(
                        "cleanup.recovery.indeterminate",
                        phase="cleanup",
                        outcome="broken",
                        cleanup_id=str(obligation.get("cleanup_id") or ""),
                        details={
                            "recovery_id": recovery_id,
                            "error_kind": type(exc).__name__,
                        },
                    )
                else:
                    journal.after(
                        obligation_id,
                        status=outcome.status,
                        request_sent=True,
                    )
        summary = journal.summary()
        status = "complete" if summary.status == "not_required" else summary.status
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
        manifest["cleanup_status"] = summary.status
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

    def _manual_reapproval_required(
        self,
        *,
        command: ResumeApiCleanupCommand,
        workspace_root: Path,
        execution_root: Path,
        manifest_path: Path,
        manifest: dict[str, Any],
        journal: EncryptedCleanupJournal,
        writer: ApiExecutionEventWriter,
        recovery_id: str,
        original_policy_sha256: str,
        current_policy_sha256: str,
    ) -> ResumeApiCleanupResult:
        status = "manual_reapproval_required"
        reason = "SAFETY_POLICY_CHANGED"
        summary = journal.summary()
        cleanup_summary_path = execution_root / "cleanup-summary.json"
        atomic_json(cleanup_summary_path, summary.model_dump(mode="json"))
        writer.emit(
            "cleanup.manual_review_required",
            phase="cleanup",
            outcome="pending",
            details={
                "recovery_id": recovery_id,
                "reason": reason,
                "original_policy_sha256": original_policy_sha256,
                "current_policy_sha256": current_policy_sha256,
            },
        )
        writer.emit(
            "cleanup.recovery.finished",
            phase="cleanup",
            outcome="pending",
            details={"recovery_id": recovery_id, "status": status},
        )
        manifest["cleanup_recovery"] = {
            "recovery_id": recovery_id,
            "status": status,
            "completed_at": datetime.now(tz=UTC).isoformat(),
            "reason": reason,
            "original_policy_sha256": original_policy_sha256,
            "current_policy_sha256": current_policy_sha256,
        }
        manifest["cleanup_status"] = status
        manifest["event_log_sha256"] = _sha256(execution_root / "execution-events.jsonl")
        manifest["cleanup_summary_sha256"] = _sha256(cleanup_summary_path)
        manifest["cleanup_journal_sha256"] = _sha256(journal.path)
        atomic_json(manifest_path, manifest)
        return ResumeApiCleanupResult(
            workspace_id=command.workspace_id,
            execution_id=command.execution_id,
            recovery_id=recovery_id,
            status=status,
            cleanup_summary_path=cleanup_summary_path.relative_to(workspace_root).as_posix(),
            summary=summary,
            original_policy_sha256=original_policy_sha256,
            current_policy_sha256=current_policy_sha256,
            reason=reason,
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


def _failed_report_result(
    _workspace_root: Path,
    workspace_id: str,
    execution_id: str,
    _results_path: Path,
    error: Exception,
) -> GenerateApiAllureReportResult:
    return GenerateApiAllureReportResult(
        workspace_id=workspace_id,
        execution_id=execution_id,
        status="failed",
        allure_results_path=None,
        allure_report_path=None,
        message="reporting failed without changing execution truth",
        error_kind=type(error).__name__,
    )


def _safe_report_event(
    writer: ApiExecutionEventWriter | None,
    result: GenerateApiAllureReportResult,
) -> str | None:
    if writer is None:
        return "ReportEventWriterUnavailable"
    try:
        writer.emit(
            "report.finished",
            phase="report",
            outcome=(
                "passed"
                if result.status == "generated"
                else "pending"
                if result.status == "results_only"
                else "broken"
            ),
            details={"status": result.status, "error_kind": result.error_kind},
        )
    except Exception as exc:
        return type(exc).__name__
    return None


def _update_report_manifest(
    manifest: dict[str, Any],
    *,
    workspace_root: Path,
    execution_root: Path,
    report_summary: ApiReportSummary,
    result: GenerateApiAllureReportResult,
) -> None:
    event_log_path = execution_root / "execution-events.jsonl"
    summary_path = execution_root / "summary.md"
    report_summary_path = execution_root / "report-summary.json"
    results_path = execution_root / "allure-results"
    report_path = execution_root / "allure-report"
    history_path = workspace_root / "allure-history.jsonl"
    manifest.update(
        {
            "summary_path": _existing_relative(summary_path, workspace_root),
            "summary_sha256": _sha256(summary_path) if summary_path.is_file() else None,
            "report_summary_path": _existing_relative(report_summary_path, workspace_root),
            "report_summary_sha256": (
                _sha256(report_summary_path) if report_summary_path.is_file() else None
            ),
            "allure_results_path": _existing_relative(results_path, workspace_root, directory=True),
            "allure_results_sha256": (
                _tree_sha256(results_path) if results_path.is_dir() else None
            ),
            "allure_report_path": _existing_relative(report_path, workspace_root, directory=True),
            "allure_report_sha256": (_tree_sha256(report_path) if report_path.is_dir() else None),
            "allure_history_path": (
                history_path.relative_to(workspace_root).as_posix()
                if history_path.is_file()
                else None
            ),
            "report_status": result.status,
            "report_error_kind": result.error_kind,
            "report_summary": report_summary.counts.model_dump(mode="json"),
            "event_log_sha256": _sha256(event_log_path) if event_log_path.is_file() else None,
        }
    )


def _existing_relative(
    path: Path,
    root: Path,
    *,
    directory: bool = False,
) -> str | None:
    exists = path.is_dir() if directory else path.is_file()
    return path.relative_to(root).as_posix() if exists else None


def _reporting_outcome(
    result: GenerateApiAllureReportResult,
    *,
    workspace_root: Path,
    execution_root: Path,
) -> _ReportingPhaseOutcome:
    try:
        event_log_path = _existing_relative(
            execution_root / "execution-events.jsonl", workspace_root
        )
        summary_path = _existing_relative(execution_root / "summary.md", workspace_root)
        report_summary_path = _existing_relative(
            execution_root / "report-summary.json", workspace_root
        )
        allure_results_path = _existing_relative(
            execution_root / "allure-results", workspace_root, directory=True
        )
        allure_report_path = _existing_relative(
            execution_root / "allure-report", workspace_root, directory=True
        )
    except Exception as exc:
        failed_result = GenerateApiAllureReportResult(
            workspace_id=result.workspace_id,
            execution_id=result.execution_id,
            status="failed",
            message="report path inspection failed without changing execution truth",
            error_kind=type(exc).__name__,
        )
        return _ReportingPhaseOutcome(
            result=failed_result,
            event_log_path=None,
            summary_path=None,
            report_summary_path=None,
            allure_results_path=None,
            allure_report_path=None,
        )
    truthful_result = result.model_copy(
        update={
            "allure_results_path": allure_results_path,
            "allure_report_path": allure_report_path,
        }
    )
    return _ReportingPhaseOutcome(
        result=truthful_result,
        event_log_path=event_log_path,
        summary_path=summary_path,
        report_summary_path=report_summary_path,
        allure_results_path=allure_results_path,
        allure_report_path=allure_report_path,
    )


def _validate_report_evidence(
    evidence: ExecutionEvidence,
    snapshot: ExecutionSourceSnapshot,
) -> None:
    if (
        evidence.run_id != snapshot.execution_id
        or evidence.environment.name != snapshot.environment
        or evidence.source_cases_path != snapshot.source_history_path
    ):
        raise ExecutionSourceLinkageError("Evidence differs from execution plan")


def _event_callback(writer: ApiExecutionEventWriter):
    def emit(event_type: str, payload: dict[str, Any]) -> None:
        status = str(payload.pop("status", ""))
        passed = payload.get("passed")
        if passed is False:
            outcome = "failed"
        elif event_type.endswith(".failed") or status in {"failed", "error", "blocked"}:
            outcome = "broken" if status != "failed" else "failed"
        elif event_type.endswith(".indeterminate"):
            outcome = "broken"
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
    source_cases_schema_version: str,
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
        source_cases_schema_version=source_cases_schema_version,
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
    execution_id: str,
    environment: str,
    evidence: ExecutionEvidence,
    report: ApiReportSummary,
    cleanup: CleanupJournalSummary,
) -> str:
    summary = report.counts
    lines = [
        "# API trial run summary",
        "",
        f"- Execution ID: `{execution_id}`",
        f"- Environment: `{environment}`",
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
