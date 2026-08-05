from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.domain.models import (
    ExecuteApiCasesCommand,
    ExecutionEnvironmentPolicy,
    ExecutionProfile,
    RunApiScenarioCommand,
)
from harness.domain.schemas.api_scenario import RunApiScenarioResult
from harness.domain.schemas.execution_evidence import ExecutionEvidence
from harness.infrastructure.api_automation import FilesystemApiAutomationService
from harness.infrastructure.persistence.common import atomic_json, atomic_text, exclusive_file_lock
from harness.infrastructure.persistence.filesystem import FilesystemStore

UTC = timezone.utc
MANIFEST_SCHEMA = "agentic-qa.harness.api-execution-manifest.v1"


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
            manifest: dict[str, Any] = {
                "schema_version": MANIFEST_SCHEMA,
                "workspace_id": command.workspace_id,
                "execution_id": command.execution_id,
                "environment": command.environment,
                "status": "started",
                "started_at": datetime.now(tz=UTC).isoformat(),
                "source_cases_path": "published/api_test_draft/current.yml",
                "source_cases_sha256": None,
                "evidence_path": None,
                "summary_path": None,
            }
            atomic_json(manifest_path, manifest)
            try:
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
                manifest["source_cases_path"] = preflight.source_cases_path
                manifest["source_cases_sha256"] = preflight.source_cases_sha256
                atomic_json(manifest_path, manifest)
            except Exception as exc:
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
                evidence = self._automation.execute(execute_command)
                result_status = _result_status(evidence)
                atomic_json(evidence_path, evidence.model_dump(mode="json"))
                atomic_text(summary_path, _render_summary(command, evidence, result_status))
            except BaseException as exc:
                manifest.update(
                    {
                        "status": "indeterminate",
                        "observed_at": datetime.now(tz=UTC).isoformat(),
                        "error_kind": type(exc).__name__,
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
                    "summary_path": summary_path.relative_to(workspace_root).as_posix(),
                    "summary": evidence.summary.model_dump(mode="json"),
                }
            )
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
                evidence=evidence,
            )

    def _profile(self, command: RunApiScenarioCommand) -> ExecutionProfile:
        payload = self._store.workspace_config(command.workspace_id)
        execution = payload.get("execution") or {}
        environments = execution.get("environments") if isinstance(execution, dict) else None
        if not isinstance(environments, dict) or command.environment not in environments:
            raise PermissionError(
                f"execution environment is not configured in workspace.yml: {command.environment}"
            )
        policy = ExecutionEnvironmentPolicy.model_validate(environments[command.environment])
        if policy.base_url_env is None:
            raise ValueError("API scenario environment requires base_url_env")
        return ExecutionProfile(
            environment=command.environment,
            base_url_env=policy.base_url_env,
            allowed_http_methods=policy.allowed_http_methods,
            allow_ui_mutations=False,
            request_timeout_seconds=policy.max_request_timeout_seconds,
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


def _result_status(evidence: ExecutionEvidence) -> str:
    summary = evidence.summary
    return (
        "passed"
        if summary.failed == 0 and summary.errors == 0 and summary.blocked == 0
        else "failed"
    )


def _render_summary(
    command: RunApiScenarioCommand,
    evidence: ExecutionEvidence,
    status: str,
) -> str:
    summary = evidence.summary
    lines = [
        "# API trial run summary",
        "",
        f"- Execution ID: `{command.execution_id}`",
        f"- Environment: `{command.environment}`",
        f"- Result: `{status}`",
        f"- Started: `{evidence.started_at.isoformat()}`",
        f"- Completed: `{evidence.completed_at.isoformat()}`",
        "",
        "## Counts",
        "",
        "| Total | Executed | Passed | Failed | Errors | Blocked |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {summary.total} | {summary.executed} | {summary.passed} | "
            f"{summary.failed} | {summary.errors} | {summary.blocked} |"
        ),
        "",
        "## Cases",
        "",
        "| Case ID | Method | Status | HTTP | Duration (ms) |",
        "|---|---|---|---:|---:|",
    ]
    for case in evidence.cases:
        status_code = "" if case.status_code is None else str(case.status_code)
        lines.append(
            f"| `{_markdown(case.case_id)}` | `{_markdown(case.method)}` | "
            f"`{case.status}` | {status_code} | {case.duration_ms} |"
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
