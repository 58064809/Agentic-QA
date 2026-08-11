from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.domain.schemas.api_execution_reporting import (
    ApiExecutionEvent,
    ApiReportCase,
    ApiReportCounts,
    ApiReportSummary,
    CleanupJournalSummary,
    GenerateApiAllureReportResult,
)
from harness.domain.schemas.api_test_cases import ApiTestCase
from harness.domain.schemas.execution_evidence import CaseExecutionEvidence, ExecutionEvidence
from harness.infrastructure.persistence.common import atomic_json, atomic_text

UTC = timezone.utc
_ALLURE_NAMESPACE = uuid.UUID("11122333-4455-5677-8899-aabbccddeeff")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class ApiExecutionEventWriter:
    def __init__(self, path: Path, execution_id: str) -> None:
        self.path = path
        self.execution_id = execution_id
        self.sequence = 0
        self.previous_hash: str | None = None
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = read_execution_events(path)
        if path.is_file():
            canonical = "".join(item.model_dump_json() + "\n" for item in existing)
            if path.read_text(encoding="utf-8") != canonical:
                # An interrupted final write is not an event. Remove only the
                # unverifiable suffix before extending the valid hash chain.
                atomic_text(path, canonical)
        if existing:
            if existing[-1].execution_id != execution_id:
                raise ValueError("execution event log belongs to a different execution ID")
            self.sequence = existing[-1].sequence
            self.previous_hash = existing[-1].event_sha256

    def emit(
        self,
        event_type: str,
        *,
        phase: str,
        outcome: str,
        case_id: str | None = None,
        dataset_id: str | None = None,
        cleanup_id: str | None = None,
        duration_ms: int | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> ApiExecutionEvent:
        self.sequence += 1
        payload: dict[str, Any] = {
            "schema_version": "agentic-qa.api-execution-events.v1",
            "sequence": self.sequence,
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "execution_id": self.execution_id,
            "event_type": event_type,
            "phase": phase,
            "outcome": outcome,
            "case_id": case_id,
            "dataset_id": dataset_id,
            "cleanup_id": cleanup_id,
            "duration_ms": duration_ms,
            "status_code": status_code,
            "details": details or {},
            "previous_event_sha256": self.previous_hash,
        }
        normalized = ApiExecutionEvent.model_validate({**payload, "event_sha256": "0" * 64})
        digest = hashlib.sha256(
            _canonical_json(normalized.model_dump(mode="json", exclude={"event_sha256"}))
        ).hexdigest()
        event = normalized.model_copy(update={"event_sha256": digest})
        line = event.model_dump_json() + "\n"
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        self.previous_hash = digest
        return event


def read_execution_events(path: Path) -> list[ApiExecutionEvent]:
    if not path.is_file():
        return []
    events: list[ApiExecutionEvent] = []
    previous: str | None = None
    execution_id: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            event = ApiExecutionEvent.model_validate_json(raw_line)
        except ValueError:
            break
        payload = event.model_dump(mode="json", exclude={"event_sha256"})
        digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
        if execution_id is None:
            execution_id = event.execution_id
        if (
            digest != event.event_sha256
            or event.previous_event_sha256 != previous
            or event.sequence != len(events) + 1
            or event.execution_id != execution_id
        ):
            break
        events.append(event)
        previous = event.event_sha256
    return events


def _base_case_id(case_id: str) -> str:
    return case_id.split("::", 1)[0]


def build_report_summary(
    evidence: ExecutionEvidence,
    cases: list[ApiTestCase],
    events: list[ApiExecutionEvent] | None = None,
    cleanup_summary: CleanupJournalSummary | None = None,
) -> ApiReportSummary:
    definitions = {case.id: case for case in cases}
    report_cases: list[ApiReportCase] = []
    cleanup_failures: list[CaseExecutionEvidence] = []
    authentication_failed = any(
        event.event_type == "authentication.failed" for event in (events or [])
    )
    for item in evidence.cases:
        if "::cleanup::" in item.case_id:
            if item.status != "passed":
                cleanup_failures.append(item)
            continue
        definition = definitions.get(_base_case_id(item.case_id))
        if item.status == "passed":
            status, reason = "passed", "ASSERTIONS_PASSED"
        elif item.status == "failed":
            status, reason = "failed", "ASSERTION_FAILED"
        elif item.status == "error":
            status, reason = "broken", "EXECUTION_ERROR"
        elif authentication_failed:
            status, reason = "skipped", "AUTHENTICATION_SETUP_FAILED"
        elif definition is not None and definition.contract_status != "confirmed":
            status, reason = "skipped", "NOT_INDEPENDENTLY_EXECUTABLE"
        else:
            status, reason = "broken", "EXECUTION_BLOCKED"
        report_cases.append(
            ApiReportCase(
                case_id=item.case_id,
                title=item.title,
                status=status,
                reason_code=reason,
                evidence_status=item.status,
            )
        )
    cleanup_incomplete = cleanup_summary is not None and cleanup_summary.status not in {
        "complete",
        "not_required",
    }
    if cleanup_failures or cleanup_incomplete:
        reason_code = (
            "CLEANUP_INDETERMINATE"
            if cleanup_summary is not None and cleanup_summary.status == "indeterminate"
            else "CLEANUP_INCOMPLETE"
        )
        report_cases.append(
            ApiReportCase(
                case_id="__environment_cleanup_integrity__",
                title="Environment cleanup integrity",
                status="broken",
                reason_code=reason_code,
            )
        )
    if authentication_failed:
        report_cases.append(
            ApiReportCase(
                case_id="__project_authentication__",
                title="Project authentication",
                status="broken",
                reason_code="AUTHENTICATION_FAILED",
            )
        )
    counts = {
        name: sum(item.status == name for item in report_cases)
        for name in ("passed", "failed", "broken", "skipped")
    }
    result = "passed" if counts["failed"] == 0 and counts["broken"] == 0 else "failed"
    return ApiReportSummary(
        execution_id=evidence.run_id,
        environment=evidence.environment.name,
        result=result,
        counts=ApiReportCounts(total=len(report_cases), **counts),
        cases=report_cases,
    )


def _millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _allure_status(case: ApiReportCase) -> str:
    return case.status


def _priority(case: ApiTestCase | None) -> str:
    return {"P0": "blocker", "P1": "critical", "P2": "normal", "P3": "minor"}.get(
        case.priority if case else "P2",
        "normal",
    )


def _safe_case_attachment(item: CaseExecutionEvidence) -> dict[str, Any]:
    return {
        "method": item.method,
        "path_template": item.path,
        "status_code": item.status_code,
        "duration_ms": item.duration_ms,
        "assertions": [assertion.model_dump(mode="json") for assertion in item.assertions],
        "error": item.error,
    }


def _event_case_id(event: ApiExecutionEvent) -> str | None:
    if event.case_id is None:
        return None
    return f"{event.case_id}::{event.dataset_id}" if event.dataset_id else event.case_id


def _allure_event_step(event: ApiExecutionEvent) -> dict[str, Any] | None:
    names = {
        "request.preparing": "Prepare request",
        "isolation.applied": "Apply execution namespace",
        "idempotency.configured": "Configure idempotency",
        "request.sent": "Send request",
        "response.received": "Receive response",
        "assertion.finished": "Evaluate assertion",
        "extraction.finished": "Extract variables",
    }
    name = names.get(event.event_type)
    if name is None or event.cleanup_id is not None:
        return None
    if event.event_type == "assertion.finished":
        assertion_type = event.details.get("assertion_type")
        name = f"Assert {assertion_type}" if assertion_type else name
    elif event.event_type == "extraction.finished":
        names_only = event.details.get("extracted_names")
        if isinstance(names_only, list) and names_only:
            name = "Extract variables: " + ", ".join(str(item) for item in names_only)
    start = _millis(event.timestamp)
    stop = start + (event.duration_ms or 0)
    status = {
        "failed": "failed",
        "broken": "broken",
        "skipped": "skipped",
    }.get(event.outcome, "passed")
    return {
        "name": name,
        "status": status,
        "stage": "finished",
        "start": start,
        "stop": stop,
    }


def write_allure_results(
    *,
    results_path: Path,
    evidence: ExecutionEvidence,
    summary: ApiReportSummary,
    cases: list[ApiTestCase],
    service: str,
    source_sha256: str,
    events: list[ApiExecutionEvent],
) -> None:
    results_path.mkdir(parents=True, exist_ok=False)
    definitions = {case.id: case for case in cases}
    evidence_by_id = {item.case_id: item for item in evidence.cases}
    result_uuids: dict[str, str] = {}
    for report_case in summary.cases:
        result_uuid = str(uuid.uuid5(_ALLURE_NAMESPACE, f"{evidence.run_id}:{report_case.case_id}"))
        result_uuids[report_case.case_id] = result_uuid
        definition = definitions.get(_base_case_id(report_case.case_id))
        item = evidence_by_id.get(report_case.case_id)
        start = _millis(item.started_at if item else evidence.started_at)
        stop = _millis(item.completed_at if item else evidence.completed_at)
        steps: list[dict[str, Any]] = []
        attachments: list[dict[str, str]] = []
        if item is not None:
            case_events = [
                event for event in events if _event_case_id(event) == report_case.case_id
            ]
            event_steps = [
                step for event in case_events if (step := _allure_event_step(event)) is not None
            ]
            if event_steps:
                steps.extend(event_steps)
            else:
                for assertion in item.assertions:
                    steps.append(
                        {
                            "name": f"Assert {assertion.type}",
                            "status": "passed" if assertion.passed else "failed",
                            "stage": "finished",
                            "start": start,
                            "stop": stop,
                            "statusDetails": {"message": assertion.message},
                        }
                    )
            attachment_name = f"{result_uuid}-attachment.json"
            atomic_json(results_path / attachment_name, _safe_case_attachment(item))
            attachments.append(
                {
                    "name": "Sanitized API exchange",
                    "source": attachment_name,
                    "type": "application/json",
                }
            )
        test_case_id = hashlib.sha256(
            f"{service}:{_base_case_id(report_case.case_id)}".encode()
        ).hexdigest()
        history_id = hashlib.sha256(
            f"{service}:{evidence.environment.name}:{report_case.case_id}".encode()
        ).hexdigest()
        status_message = report_case.reason_code
        if report_case.status == "skipped" and report_case.case_id == "TC-MEMBER-LOGIN-001":
            status_message = (
                "Project authentication is executed as a setup fixture; "
                "this manual case does not send a duplicate request."
            )
        elif report_case.reason_code == "AUTHENTICATION_SETUP_FAILED":
            status_message = "Project authentication failed; dependent request was not sent."
        elif report_case.status == "skipped":
            status_message = "Pending or unconfirmed scenario is not independently executable."
        payload = {
            "uuid": result_uuid,
            "historyId": history_id,
            "testCaseId": test_case_id,
            "fullName": f"{service}.{evidence.environment.name}.{report_case.case_id}",
            "name": f"{report_case.case_id} {report_case.title}",
            "description": f"Reason: `{report_case.reason_code}`",
            "labels": [
                {"name": "parentSuite", "value": service},
                {"name": "suite", "value": "API"},
                {"name": "subSuite", "value": evidence.environment.name},
                {"name": "severity", "value": _priority(definition)},
                {"name": "environment", "value": evidence.environment.name},
                {"name": "framework", "value": "agentic-qa"},
                {"name": "language", "value": "python"},
            ],
            "status": _allure_status(report_case),
            "statusDetails": {"message": status_message},
            "stage": "finished",
            "start": start,
            "stop": stop,
            "steps": steps,
            "attachments": attachments,
        }
        atomic_json(results_path / f"{result_uuid}-result.json", payload)

    auth_events = [event for event in events if event.phase == "authentication"]
    cleanup_events = [event for event in events if event.phase == "cleanup"]
    if auth_events or cleanup_events:
        children = [
            value for case_id, value in result_uuids.items() if not case_id.startswith("__")
        ]
        container_uuid = str(uuid.uuid5(_ALLURE_NAMESPACE, f"{evidence.run_id}:fixtures"))
        container: dict[str, Any] = {
            "uuid": container_uuid,
            "children": children,
            "befores": [],
            "afters": [],
            "start": _millis(evidence.started_at),
            "stop": _millis(evidence.completed_at),
        }
        if auth_events:
            final = auth_events[-1]
            container["befores"].append(
                {
                    "name": "Project authentication",
                    "status": "passed" if final.outcome == "passed" else "broken",
                    "stage": "finished",
                    "start": _millis(auth_events[0].timestamp),
                    "stop": _millis(final.timestamp),
                }
            )
        for event in cleanup_events:
            if event.event_type != "cleanup.finished":
                continue
            container["afters"].append(
                {
                    "name": f"Cleanup {event.cleanup_id or event.case_id or ''}".strip(),
                    "status": "passed" if event.outcome == "passed" else "broken",
                    "stage": "finished",
                    "start": _millis(event.timestamp),
                    "stop": _millis(event.timestamp),
                }
            )
        atomic_json(results_path / f"{container_uuid}-container.json", container)

    atomic_text(
        results_path / "environment.properties",
        "\n".join(
            [
                f"service={service}",
                f"environment={evidence.environment.name}",
                f"source_cases_sha256={source_sha256}",
                "response_bodies=omitted",
                "request_values=omitted",
                "",
            ]
        ),
    )


def find_allure_cli(repo_root: Path) -> Path | None:
    local = repo_root / "node_modules" / "allure" / "cli.js"
    if local.is_file():
        return local
    found = shutil.which("allure")
    if found is None or (os.name == "nt" and Path(found).suffix.lower() == ".cmd"):
        return None
    return Path(found)


def generate_allure_html(
    *,
    repo_root: Path,
    workspace_id: str,
    execution_id: str,
    results_path: Path,
    report_path: Path,
) -> GenerateApiAllureReportResult:
    cli = find_allure_cli(repo_root)
    relative_results = results_path.relative_to(repo_root / "workspaces" / workspace_id)
    if cli is None:
        return GenerateApiAllureReportResult(
            workspace_id=workspace_id,
            execution_id=execution_id,
            status="results_only",
            allure_results_path=relative_results.as_posix(),
            message="Allure CLI is unavailable; run npm ci and api report allure",
        )
    command = [str(cli), "generate", str(results_path)]
    if cli.suffix == ".js":
        node = shutil.which("node")
        if node is None:
            return GenerateApiAllureReportResult(
                workspace_id=workspace_id,
                execution_id=execution_id,
                status="results_only",
                allure_results_path=relative_results.as_posix(),
                message="Node.js is unavailable; install Node.js and rerun api report allure",
            )
        command.insert(0, node)
    config_path = repo_root / "allure.config.mjs"
    command.extend(["--config", str(config_path), "--output", str(report_path)])
    environment = os.environ.copy()
    environment["AGENTIC_QA_ALLURE_HISTORY_PATH"] = str(
        repo_root / "workspaces" / workspace_id / "allure-history.jsonl"
    )
    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GenerateApiAllureReportResult(
            workspace_id=workspace_id,
            execution_id=execution_id,
            status="failed",
            allure_results_path=relative_results.as_posix(),
            message="Allure HTML generation failed; rerun api report allure",
            error_kind=type(exc).__name__,
        )
    if completed.returncode != 0:
        return GenerateApiAllureReportResult(
            workspace_id=workspace_id,
            execution_id=execution_id,
            status="failed",
            allure_results_path=relative_results.as_posix(),
            message="Allure HTML generation failed; rerun api report allure",
            error_kind="AllureProcessError",
        )
    workspace_root = repo_root / "workspaces" / workspace_id
    return GenerateApiAllureReportResult(
        workspace_id=workspace_id,
        execution_id=execution_id,
        status="generated",
        allure_results_path=relative_results.as_posix(),
        allure_report_path=report_path.relative_to(workspace_root).as_posix(),
    )
