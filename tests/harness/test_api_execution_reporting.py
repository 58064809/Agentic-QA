from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness.domain.schemas.api_execution_reporting import ApiReportSummary
from harness.domain.schemas.api_test_cases import ApiCleanupStep, ApiTestCase
from harness.domain.schemas.execution_evidence import (
    CaseExecutionEvidence,
    ExecutionEnvironment,
    ExecutionEvidence,
    ExecutionSummary,
)
from harness.infrastructure.api_cleanup_journal import EncryptedCleanupJournal
from harness.infrastructure.api_execution_reporting import (
    ApiExecutionEventWriter,
    build_report_summary,
    find_allure_cli,
    generate_allure_html,
    read_execution_events,
    write_allure_results,
)

UTC = timezone.utc


def _case(case_id: str, *, confirmed: bool) -> ApiTestCase:
    request = {"method": "GET", "path": "/items"} if confirmed else {}
    return ApiTestCase.model_validate(
        {
            "id": case_id,
            "title": case_id,
            "priority": "P1",
            "contract_status": "confirmed" if confirmed else "pending_confirmation",
            "business_rule_refs": ["RULE-1"],
            "review_status": "needs_human_review",
            "review_questions": ["review"],
            "source_refs": [
                {
                    "source_type": "openapi" if confirmed else "manual-test-case",
                    "source_path": "source.yml",
                    "chunk_id": case_id,
                    "locator": "GET /items" if confirmed else case_id,
                    "summary": "source",
                    "confidence": "high",
                }
            ],
            "pending": [] if confirmed else ["handled by authentication fixture"],
            "request": request,
            "assertions": ([{"type": "status_code", "expected": 200}] if confirmed else []),
            "variables": {"datasets": [], "extract": {}},
            "cleanup": [],
        }
    )


def _evidence() -> ExecutionEvidence:
    now = datetime.now(tz=UTC)
    cases = [
        CaseExecutionEvidence(
            case_id="TC-MEMBER-LOGIN-001",
            title="login",
            method="",
            path="",
            status="blocked",
            started_at=now,
            completed_at=now,
            duration_ms=0,
            error="API contract is not confirmed",
        ),
        CaseExecutionEvidence(
            case_id="TC-READ-001",
            title="read",
            method="GET",
            path="/items",
            status="passed",
            started_at=now,
            completed_at=now,
            duration_ms=12,
            status_code=200,
        ),
    ]
    return ExecutionEvidence(
        schema_version="agentic-qa.execution-evidence.v1",
        run_id="trial-1",
        source_cases_path="published/api_test_draft/current.yml",
        source_cases_schema_version="agentic-qa.api-cases.v1.1",
        started_at=now,
        completed_at=now,
        environment=ExecutionEnvironment(
            name="dev",
            base_url_env="LOCAL_BASE_URL",
            base_url_configured=True,
            allowed_methods=["GET"],
            request_timeout_seconds=10,
        ),
        summary=ExecutionSummary(
            total=2,
            executed=1,
            passed=1,
            failed=0,
            errors=0,
            blocked=1,
        ),
        cases=cases,
    )


def test_pending_login_maps_to_skipped_without_failing_run(tmp_path: Path) -> None:
    evidence = _evidence()
    cases = [_case("TC-MEMBER-LOGIN-001", confirmed=False), _case("TC-READ-001", confirmed=True)]

    summary = build_report_summary(evidence, cases)

    assert isinstance(summary, ApiReportSummary)
    assert summary.result == "passed"
    assert summary.counts.passed == 1
    assert summary.counts.skipped == 1
    assert summary.counts.broken == 0

    results = tmp_path / "allure-results"
    write_allure_results(
        results_path=results,
        evidence=evidence,
        summary=summary,
        cases=cases,
        service="member-service",
        source_sha256="a" * 64,
        events=[],
    )
    payloads = [
        json.loads(path.read_text(encoding="utf-8")) for path in results.glob("*-result.json")
    ]
    statuses = {item["name"].split()[0]: item["status"] for item in payloads}
    assert statuses == {"TC-MEMBER-LOGIN-001": "skipped", "TC-READ-001": "passed"}


def test_execution_event_log_is_hash_chained_and_ignores_corrupt_tail(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    writer = ApiExecutionEventWriter(path, "trial-1")
    first = writer.emit("execution.started", phase="execution", outcome="started")
    second = writer.emit("execution.finished", phase="execution", outcome="passed")

    assert second.previous_event_sha256 == first.event_sha256
    assert [item.sequence for item in read_execution_events(path)] == [1, 2]

    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"truncated":')
    assert [item.sequence for item in read_execution_events(path)] == [1, 2]
    resumed = ApiExecutionEventWriter(path, "trial-1")
    resumed.emit("report.finished", phase="report", outcome="passed")
    assert [item.sequence for item in read_execution_events(path)] == [1, 2, 3]


def test_authentication_failure_is_one_broken_fixture_with_skipped_dependencies(
    tmp_path: Path,
) -> None:
    evidence = _evidence().model_copy(
        update={
            "cases": [item.model_copy(update={"status": "blocked"}) for item in _evidence().cases],
            "summary": ExecutionSummary(
                total=2,
                executed=0,
                passed=0,
                failed=0,
                errors=0,
                blocked=2,
            ),
        }
    )
    writer = ApiExecutionEventWriter(tmp_path / "events.jsonl", "trial-1")
    writer.emit(
        "authentication.failed",
        phase="authentication",
        outcome="broken",
        details={"error_kind": "ApiAuthenticationError"},
    )

    summary = build_report_summary(
        evidence,
        [_case("TC-MEMBER-LOGIN-001", confirmed=False), _case("TC-READ-001", confirmed=True)],
        read_execution_events(writer.path),
    )

    assert summary.result == "failed"
    assert summary.counts.skipped == 2
    assert summary.counts.broken == 1
    assert summary.cases[-1].case_id == "__project_authentication__"


def test_cleanup_journal_encrypts_runtime_values_and_tracks_exactly_once(tmp_path: Path) -> None:
    key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    path = tmp_path / ".cleanup-journal.enc"
    journal = EncryptedCleanupJournal(
        path,
        key=key,
        workspace_id="demo",
        execution_id="trial-1",
        environment="qa",
        source_cases_sha256="a" * 64,
        structural_sha256="sha256:" + "b" * 64,
    )
    step = ApiCleanupStep.model_validate(
        {
            "id": "delete-item",
            "request": {"method": "DELETE", "path": "/items/${{item_id}}"},
            "assertions": [{"type": "status_code", "expected": 204}],
        }
    )
    obligation = journal.register(
        case_id="CREATE-1",
        title="create",
        cleanup=step,
        runtime_variables={"item_id": "private-business-id"},
    )

    assert "private-business-id" not in path.read_text(encoding="utf-8")
    assert journal.summary().status == "pending"
    journal.before(obligation)
    assert journal.summary().status == "indeterminate"
    with pytest.raises(ValueError, match="not pending"):
        journal.before(obligation)
    journal.after(obligation, status="passed", request_sent=True)
    assert journal.summary().status == "complete"

    loaded = EncryptedCleanupJournal.load(path, key=key)
    assert loaded.summary().counts.completed == 1
    with pytest.raises(ValueError, match="cannot be decrypted"):
        EncryptedCleanupJournal.load(
            path,
            key=base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"),
        )


def test_pinned_allure_cli_generates_html_and_workspace_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = Path.cwd()
    cli = find_allure_cli(repository_root)
    if cli is None:
        pytest.skip("pinned Allure CLI is not installed; run npm ci")
    isolated_root = tmp_path / "repo"
    isolated_root.mkdir()
    workspace_root = isolated_root / "workspaces" / "demo"
    results_path = workspace_root / "executions" / "execution-1" / "allure-results"
    report_path = workspace_root / "executions" / "execution-1" / "allure-report"
    results_path.mkdir(parents=True)
    (results_path / "environment.properties").write_text(
        "service=compatibility\n", encoding="utf-8"
    )
    (results_path / "compatibility-result.json").write_text(
        json.dumps(
            {
                "uuid": "013d61a6-3edf-41dd-b8bd-3de948c9dd8f",
                "historyId": "history-1",
                "testCaseId": "test-case-1",
                "fullName": "compatibility.api.report",
                "name": "Allure compatibility",
                "status": "passed",
                "stage": "finished",
                "start": 1,
                "stop": 2,
            }
        ),
        encoding="utf-8",
    )
    allure_module = (repository_root / "node_modules" / "allure" / "dist" / "index.js").as_uri()
    (isolated_root / "allure.config.mjs").write_text(
        "\n".join(
            [
                f'import {{ defineConfig }} from "{allure_module}";',
                "export default defineConfig({",
                "  historyPath: process.env.AGENTIC_QA_ALLURE_HISTORY_PATH,",
                "  plugins: { awesome: {} },",
                "});",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "harness.infrastructure.api_execution_reporting.find_allure_cli",
        lambda _root: cli,
    )

    result = generate_allure_html(
        repo_root=isolated_root,
        workspace_id="demo",
        execution_id="execution-1",
        results_path=results_path,
        report_path=report_path,
    )

    assert result.status == "generated"
    assert (report_path / "index.html").is_file()
    assert (workspace_root / "allure-history.jsonl").is_file()
