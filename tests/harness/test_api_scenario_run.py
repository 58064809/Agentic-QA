from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from harness import (
    ApiExecutionPlan,
    CreateWorkspaceCommand,
    GenerateApiAllureReportCommand,
    Harness,
    ResumeApiCleanupCommand,
    RunApiScenarioCommand,
)
from harness.domain.schemas.api_test_cases import ApiCleanupStep, ApiTestCasesDraft
from harness.infrastructure.api_cleanup_journal import EncryptedCleanupJournal
from harness.infrastructure.api_execution_plan import build_api_execution_plan
from harness.infrastructure.api_execution_snapshot import (
    ExecutionPlanTamperedError,
    ExecutionSourceLinkageError,
)
from harness.infrastructure.local_config import FilesystemLocalConfigLoader


class _Response:
    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        self.url = url
        self.headers = {"X-Business": "private-header-value"}

    def json(self) -> object:
        return {
            "message": "private-business-value",
            "token": "response-secret-value",
        }


def _publish_version(root: Path, draft: ApiTestCasesDraft, run_id: str) -> Path:
    published = root / "published" / "api_test_draft"
    published.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(
        draft.model_dump(mode="json"), allow_unicode=True, sort_keys=False
    ).encode()
    current = published / "current.yml"
    current.write_bytes(content)
    history = published / "history"
    history.mkdir(exist_ok=True)
    history_target = history / f"{run_id}.yml"
    history_target.write_bytes(content)
    index_path = history / "index.yml"
    index = (
        yaml.safe_load(index_path.read_text(encoding="utf-8"))
        if index_path.is_file()
        else {"schema_version": "agentic-qa.harness.history.v2", "versions": []}
    )
    index["versions"].append(
        {
            "run_id": run_id,
            "variant": "raw",
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "assessment_key": "unit",
            "path": f"published/api_test_draft/history/{run_id}.yml",
            "attachments": {},
            "published_at": "2026-01-01T00:00:00+00:00",
        }
    )
    index_path.write_text(yaml.safe_dump(index, sort_keys=False), encoding="utf-8")
    return current


def _workspace(
    tmp_path: Path,
    *,
    expected_status: int = 201,
    with_cleanup: bool = False,
) -> Path:
    source = tmp_path / "local-sources" / "api" / "demo"
    source.mkdir(parents=True)
    local_config = {
        "schema_version": "agentic-qa.local-config.v2",
        "model": {
            "provider": "recorded",
            "api_key_env": "UNIT_MODEL_KEY",
            "flash_model": "recorded-flash",
            "pro_model": "recorded-pro",
            "base_url": "https://model.example.test",
        },
        "rag": {},
        "system_database": {
            "host": "localhost",
            "port": 5432,
            "database": "postgres",
            "user": "postgres",
            "password": "unit-only",
        },
        "test_management": {"provider": "none"},
        "workspace_defaults": {},
        "runtime": {
            "cleanup_journal_key": (
                base64.urlsafe_b64encode(os.urandom(32)).decode("ascii") if with_cleanup else ""
            )
        },
        "api": {
            "services": {
                "demo": {
                    "source_directory": "local-sources/api/demo",
                    "environments": {
                        "qa": {
                            "base_url": "https://qa.example.test",
                            "trusted_origins": ["https://qa.example.test"],
                            "allowed_http_methods": (
                                ["POST", "DELETE"] if with_cleanup else ["POST"]
                            ),
                            "cleanup_exempt_operations": ([] if with_cleanup else ["POST /orders"]),
                            "timeout_seconds": 7,
                            "auth": {
                                "login": None,
                                "fallback_token": "local-runtime-token",
                                "fallback_injection": {
                                    "location": "header",
                                    "name": "Authorization",
                                    "prefix": "Bearer",
                                },
                            },
                        }
                    },
                }
            }
        },
    }
    (tmp_path / "agentic-qa.local.yml").write_text(
        yaml.safe_dump(local_config, sort_keys=False), encoding="utf-8"
    )
    FilesystemLocalConfigLoader(tmp_path).migrate_inline_secrets()
    harness = Harness(tmp_path)
    root = harness.create_workspace(CreateWorkspaceCommand(workspace_id="demo"))
    loader = FilesystemLocalConfigLoader(tmp_path)
    project = loader.resolve_api_project(loader.load_required(), "demo", "qa")
    config_path = root / "workspace.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["execution"]["environments"]["qa"] = project.policy.model_dump(
        mode="json", exclude_none=True
    )
    config["api_project"] = {
        "service": "demo",
        "environment": "qa",
        "structural_sha256": project.structural_sha256,
    }
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    openapi_ref = {
        "source_type": "openapi",
        "source_path": "sources/openapi.yml",
        "chunk_id": "POST /orders",
        "locator": "POST /orders",
        "summary": "create order",
        "confidence": "high",
    }
    draft = ApiTestCasesDraft.model_validate(
        {
            "schema_version": "agentic-qa.api-cases.v1.2",
            "artifact_type": "api_automation_cases",
            "status": "needs_human_review",
            "human_review_required": True,
            "business_rules": ["ORDER-001"],
            "source_refs": [openapi_ref],
            "cases": [
                {
                    "id": "api-order-create",
                    "title": "create order",
                    "priority": "P1",
                    "contract_status": "confirmed",
                    "business_rule_refs": ["ORDER-001"],
                    "review_status": "needs_human_review",
                    "review_questions": ["Review request"],
                    "source_refs": [openapi_ref],
                    "pending": [],
                    "request": {
                        "method": "POST",
                        "path": "/orders",
                        "body": {"name": "fixture-order"},
                    },
                    "assertions": [{"type": "status_code", "expected": expected_status}],
                    "variables": {
                        "datasets": [],
                        "extract": (
                            {
                                "order_id": {
                                    "source": "response_json",
                                    "path": "$.token",
                                    "required": True,
                                }
                            }
                            if with_cleanup
                            else {}
                        ),
                    },
                    "cleanup": (
                        [
                            {
                                "id": "delete-order",
                                "request": {
                                    "method": "DELETE",
                                    "path": "/orders/${{order_id}}",
                                },
                                "assertions": [{"type": "status_code", "expected": 204}],
                            }
                        ]
                        if with_cleanup
                        else []
                    ),
                }
            ],
            "review_questions": ["Review before publication"],
        }
    )
    _publish_version(root, draft, "published-v1")
    return root


def _command(execution_id: str) -> RunApiScenarioCommand:
    return RunApiScenarioCommand(
        workspace_id="demo",
        execution_id=execution_id,
        environment="qa",
    )


def test_run_persists_redacted_reports_and_never_replays_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    requests_seen: list[tuple[str, str, dict[str, object]]] = []

    def request(method: str, url: str, **kwargs: object) -> _Response:
        requests_seen.append((method, url, kwargs))
        return _Response(201, url)

    monkeypatch.setattr("requests.request", request)
    harness = Harness(tmp_path)
    result = harness.run_api_scenario(_command("trial-001"))

    assert result.schema_version == "agentic-qa.harness.run-api-scenario-result.v4"
    assert result.status == "passed"
    assert len(requests_seen) == 1
    assert requests_seen[0][2]["allow_redirects"] is False
    assert requests_seen[0][2]["timeout"] == 7
    execution_root = root / "executions" / "trial-001"
    for relative_path in (
        result.manifest_path,
        result.evidence_path,
        result.cleanup_summary_path,
        result.event_log_path,
        result.summary_path,
        result.report_summary_path,
    ):
        assert relative_path is not None
        assert (root / relative_path).is_file()
    assert result.allure_results_path is not None
    assert (root / result.allure_results_path).is_dir()
    if result.allure_report_path is not None:
        assert (root / result.allure_report_path).is_dir()
    manifest = json.loads((execution_root / "manifest.json").read_text(encoding="utf-8"))
    plan_text = (execution_root / "execution-plan.json").read_text(encoding="utf-8")
    plan = ApiExecutionPlan.model_validate_json(plan_text)
    assert manifest["status"] == "completed"
    assert manifest["result"] == "passed"
    assert manifest["execution_status"] == "completed"
    assert manifest["test_result"] == "passed"
    assert manifest["cleanup_status"] == "not_required"
    assert manifest["source_cases_sha256"] == result.source_cases_sha256
    assert manifest["execution_plan_path"].endswith("execution-plan.json")
    assert manifest["execution_plan_sha256"] == hashlib.sha256(plan_text.encode()).hexdigest()
    assert plan.source_cases_sha256 == result.source_cases_sha256
    assert plan.source_publication_id == "published-v1"
    assert plan.source_history_path.endswith("history/published-v1.yml")
    assert manifest["source_publication_id"] == "published-v1"
    assert plan.execution_id == "trial-001"
    assert [item.case_id for item in plan.cases] == ["api-order-create"]
    assert plan.cases[0].operation_classification == "mutation_no_cleanup"
    tampered_plan = plan.model_dump(mode="json")
    tampered_plan["environment"] = "tampered"
    with pytest.raises(ValueError, match="semantic hash"):
        ApiExecutionPlan.model_validate(tampered_plan)
    evidence = (execution_root / "evidence.json").read_text(encoding="utf-8")
    summary = (execution_root / "summary.md").read_text(encoding="utf-8")
    report_summary = json.loads(
        (execution_root / "report-summary.json").read_text(encoding="utf-8")
    )
    events = (execution_root / "execution-events.jsonl").read_text(encoding="utf-8")
    persisted = manifest | {
        "execution_plan": plan_text,
        "evidence": evidence,
        "summary_report": summary,
    }
    serialized = json.dumps(persisted, ensure_ascii=False)
    for secret in (
        "local-runtime-token",
        "private-header-value",
        "private-business-value",
        "response-secret-value",
    ):
        assert secret not in serialized
    assert "request data values are intentionally omitted" in summary
    assert report_summary["result"] == "passed"
    assert '"event_type":"request.sent"' in events
    assert events.index('"event_type":"mutation.intent.created"') < events.index(
        '"event_type":"request.sent"'
    )
    assert (execution_root / "allure-results").is_dir()
    result_files = list((execution_root / "allure-results").glob("*-result.json"))
    assert result_files
    allure_case = json.loads(result_files[0].read_text(encoding="utf-8"))
    assert [step["name"] for step in allure_case["steps"]] == [
        "Prepare request",
        "Send request",
        "Receive response",
        "Assert status_code",
    ]
    for hash_field in (
        "evidence_sha256",
        "summary_sha256",
        "event_log_sha256",
        "report_summary_sha256",
        "cleanup_summary_sha256",
        "allure_results_sha256",
        "execution_plan_sha256",
    ):
        assert len(manifest[hash_field]) == 64

    with pytest.raises(FileExistsError, match="will not be replayed"):
        harness.run_api_scenario(_command("trial-001"))
    assert len(requests_seen) == 1


def test_failed_assertion_is_persisted_as_failed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path, expected_status=200)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))

    result = Harness(tmp_path).run_api_scenario(_command("trial-failed"))

    assert result.status == "failed"
    assert result.evidence.summary.failed == 1
    manifest = json.loads(
        (root / "executions" / "trial-failed" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "completed"
    assert manifest["result"] == "failed"


def test_request_exception_records_indeterminate_after_mutation_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)

    def fail_request(method: str, url: str, **_kwargs: object) -> _Response:
        raise RuntimeError("transport failed after dispatch")

    monkeypatch.setattr("requests.request", fail_request)

    result = Harness(tmp_path).run_api_scenario(_command("request-indeterminate"))

    assert result.execution_status == "completed"
    assert result.test_result == "broken"
    events = [
        json.loads(line)
        for line in (root / "executions" / "request-indeterminate" / "execution-events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    event_types = [event["event_type"] for event in events]
    assert event_types.index("mutation.intent.created") < event_types.index("request.sent")
    assert event_types.index("request.sent") < event_types.index("request.indeterminate")
    indeterminate = next(
        event for event in events if event["event_type"] == "request.indeterminate"
    )
    assert indeterminate["outcome"] == "broken"


def test_allure_timeout_only_changes_report_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))
    monkeypatch.setattr(
        "harness.infrastructure.api_scenario_run.generate_allure_html",
        lambda **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd="allure", timeout=120)
        ),
    )

    result = Harness(tmp_path).run_api_scenario(_command("report-timeout"))

    assert result.status == "passed"
    assert result.execution_status == "completed"
    assert result.test_result == "passed"
    assert result.cleanup_status == "not_required"
    assert result.report_status == "failed"
    manifest = json.loads(
        (root / "executions" / "report-timeout" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["execution_status"] == "completed"
    assert manifest["test_result"] == "passed"
    assert manifest["cleanup_status"] == "not_required"
    assert manifest["report_status"] == "failed"
    assert manifest["report_error_kind"] == "TimeoutExpired"
    assert (root / "executions" / "report-timeout" / "evidence.json").is_file()


@pytest.mark.parametrize("event_type", ["report.started", "report.finished"])
def test_reporting_event_failure_does_not_change_execution_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))
    from harness.infrastructure import api_scenario_run as scenario_run

    original_emit = scenario_run.ApiExecutionEventWriter.emit

    def emit(self: object, current_type: str, **kwargs: object) -> object:
        if current_type == event_type:
            raise OSError(f"cannot persist {event_type}")
        return original_emit(self, current_type, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(scenario_run.ApiExecutionEventWriter, "emit", emit)

    result = Harness(tmp_path).run_api_scenario(
        _command(f"report-event-{event_type.rsplit('.', maxsplit=1)[-1]}")
    )

    assert result.execution_status == "completed"
    assert result.test_result == "passed"
    assert result.cleanup_status == "not_required"
    assert result.report_status == "failed"
    if event_type == "report.started":
        assert result.summary_path is None
        assert result.report_summary_path is None
        assert result.allure_results_path is None
    else:
        assert result.summary_path is not None
        assert result.report_summary_path is not None
        assert result.allure_results_path is not None
    execution_root = root / "executions" / result.execution_id
    manifest = json.loads((execution_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["execution_status"] == "completed"
    assert manifest["test_result"] == "passed"
    assert manifest["cleanup_status"] == "not_required"
    assert manifest["report_status"] == "failed"


@pytest.mark.parametrize("artifact_name", ["summary.md", "report-summary.json"])
def test_reporting_artifact_failure_does_not_change_execution_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_name: str,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))
    from harness.infrastructure import api_scenario_run as scenario_run

    function_name = "atomic_text" if artifact_name.endswith(".md") else "atomic_json"
    original_write = getattr(scenario_run, function_name)

    def write(path: Path, payload: object) -> None:
        if path.name == artifact_name:
            raise OSError(f"cannot write {artifact_name}")
        original_write(path, payload)

    monkeypatch.setattr(scenario_run, function_name, write)

    result = Harness(tmp_path).run_api_scenario(
        _command(f"report-artifact-{artifact_name.split('.')[0]}")
    )

    assert result.execution_status == "completed"
    assert result.test_result == "passed"
    assert result.cleanup_status == "not_required"
    assert result.report_status == "failed"
    if artifact_name == "summary.md":
        assert result.summary_path is None
    else:
        assert result.report_summary_path is None
    assert result.allure_results_path is None
    assert result.allure_report_path is None
    manifest = json.loads(
        (root / "executions" / result.execution_id / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["execution_status"] == "completed"
    assert manifest["test_result"] == "passed"
    assert manifest["cleanup_status"] == "not_required"


def test_allure_results_failure_does_not_change_execution_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))
    monkeypatch.setattr(
        "harness.infrastructure.api_scenario_run.write_allure_results",
        lambda **kwargs: (_ for _ in ()).throw(OSError("results unavailable")),
    )

    result = Harness(tmp_path).run_api_scenario(_command("report-results-failure"))

    assert result.execution_status == "completed"
    assert result.test_result == "passed"
    assert result.cleanup_status == "not_required"
    assert result.report_status == "failed"
    assert result.allure_results_path is None
    assert result.allure_report_path is None
    manifest = json.loads(
        (root / "executions" / result.execution_id / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["execution_status"] == "completed"
    assert manifest["test_result"] == "passed"
    assert manifest["cleanup_status"] == "not_required"


def test_report_manifest_failure_returns_failed_with_committed_execution_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))
    from harness.infrastructure import api_scenario_run as scenario_run

    original_atomic_json = scenario_run.atomic_json

    def atomic_json(path: Path, payload: object) -> None:
        if (
            path.name == "manifest.json"
            and isinstance(payload, dict)
            and payload.get("report_status") != "not_started"
        ):
            raise OSError("report manifest unavailable")
        original_atomic_json(path, payload)

    monkeypatch.setattr(scenario_run, "atomic_json", atomic_json)

    result = Harness(tmp_path).run_api_scenario(_command("report-manifest-failure"))

    assert result.execution_status == "completed"
    assert result.test_result == "passed"
    assert result.cleanup_status == "not_required"
    assert result.report_status == "failed"
    manifest = json.loads(
        (root / "executions" / result.execution_id / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["execution_status"] == "completed"
    assert manifest["test_result"] == "passed"
    assert manifest["cleanup_status"] == "not_required"


def test_report_path_inspection_failure_is_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))
    from harness.infrastructure import api_scenario_run as scenario_run

    original_existing_relative = scenario_run._existing_relative

    def existing_relative(path: Path, root_path: Path, *, directory: bool = False) -> str | None:
        if path.name == "summary.md":
            raise OSError("path metadata unavailable")
        return original_existing_relative(path, root_path, directory=directory)

    monkeypatch.setattr(scenario_run, "_existing_relative", existing_relative)

    result = Harness(tmp_path).run_api_scenario(_command("report-path-inspection-failure"))

    assert result.execution_status == "completed"
    assert result.test_result == "passed"
    assert result.cleanup_status == "not_required"
    assert result.report_status == "failed"
    assert result.event_log_path is None
    assert result.summary_path is None
    assert result.report_summary_path is None
    assert result.allure_results_path is None
    assert result.allure_report_path is None
    manifest = json.loads(
        (root / "executions" / result.execution_id / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["execution_status"] == "completed"
    assert manifest["test_result"] == "passed"
    assert manifest["cleanup_status"] == "not_required"


def test_report_failure_construction_does_not_inspect_artifact_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))
    from harness.infrastructure import api_scenario_run as scenario_run

    original_atomic_text = scenario_run.atomic_text
    original_existing_relative = scenario_run._existing_relative
    inspection_failed = False

    def atomic_text(path: Path, payload: str) -> None:
        if path.name == "summary.md":
            raise OSError("summary write unavailable")
        original_atomic_text(path, payload)

    def existing_relative(path: Path, root_path: Path, *, directory: bool = False) -> str | None:
        nonlocal inspection_failed
        if path.name == "allure-results":
            inspection_failed = True
            raise OSError("artifact path inspection unavailable")
        return original_existing_relative(path, root_path, directory=directory)

    monkeypatch.setattr(scenario_run, "atomic_text", atomic_text)
    monkeypatch.setattr(scenario_run, "_existing_relative", existing_relative)

    result = Harness(tmp_path).run_api_scenario(_command("double-report-failure"))

    assert inspection_failed is True
    assert result.execution_status == "completed"
    assert result.test_result == "passed"
    assert result.cleanup_status == "not_required"
    assert result.report_status == "failed"
    assert result.allure_results_path is None
    assert result.allure_report_path is None
    manifest = json.loads(
        (root / "executions" / result.execution_id / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["execution_status"] == "completed"
    assert manifest["test_result"] == "passed"
    assert manifest["cleanup_status"] == "not_required"


def test_execution_event_failure_remains_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _workspace(tmp_path)
    from harness.infrastructure import api_scenario_run as scenario_run

    original_emit = scenario_run.ApiExecutionEventWriter.emit

    def emit(self: object, event_type: str, **kwargs: object) -> object:
        if event_type == "execution.started":
            raise OSError("execution event unavailable")
        return original_emit(self, event_type, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(scenario_run.ApiExecutionEventWriter, "emit", emit)

    with pytest.raises(OSError, match="execution event unavailable"):
        Harness(tmp_path).run_api_scenario(_command("execution-event-strict"))


def test_mutation_is_armed_before_send_and_completed_cleanup_runs_lifo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path, with_cleanup=True)
    requests_seen: list[tuple[str, str]] = []

    def request(method: str, url: str, **_kwargs: object) -> _Response:
        requests_seen.append((method, url))
        return _Response(201 if method == "POST" else 204, url)

    monkeypatch.setattr("requests.request", request)
    result = Harness(tmp_path).run_api_scenario(_command("trial-cleanup"))

    assert result.status == "passed"
    assert requests_seen == [
        ("POST", "https://qa.example.test/orders"),
        ("DELETE", "https://qa.example.test/orders/response-secret-value"),
    ]
    execution_root = root / "executions" / "trial-cleanup"
    local = FilesystemLocalConfigLoader(tmp_path).load_required()
    journal = EncryptedCleanupJournal.load(
        execution_root / ".cleanup-journal.enc",
        key=local.runtime.cleanup_journal_key,
    )
    assert journal.summary().status == "complete"
    assert journal.summary().counts.completed == 1
    event_types = [
        json.loads(line)["event_type"]
        for line in (execution_root / "execution-events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert event_types.index("cleanup.armed") < event_types.index("request.sent")
    assert event_types.index("cleanup.registered") > event_types.index("response.received")


def test_preflight_failure_is_persisted_without_sending_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    requests_seen: list[str] = []
    local_path = tmp_path / "agentic-qa.local.yml"
    config = yaml.safe_load(local_path.read_text(encoding="utf-8"))
    config["api"]["services"]["demo"]["environments"]["qa"]["allowed_http_methods"] = ["GET"]
    local_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(
        "requests.request",
        lambda method, url, **kwargs: requests_seen.append(url),
    )

    harness = Harness(tmp_path)
    with pytest.raises(PermissionError, match="policy changed"):
        harness.run_api_scenario(_command("trial-preflight"))

    assert requests_seen == []
    manifest_path = root / "executions" / "trial-preflight" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "preflight_failed"
    assert manifest["error_kind"] == "PermissionError"
    with pytest.raises(FileExistsError, match="will not be replayed"):
        harness.run_api_scenario(_command("trial-preflight"))
    assert requests_seen == []


def test_run_rejects_missing_published_yaml_without_sending_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    (root / "published" / "api_test_draft" / "current.yml").unlink()
    requests_seen: list[str] = []
    monkeypatch.setattr(
        "requests.request",
        lambda method, url, **kwargs: requests_seen.append(url),
    )

    with pytest.raises(ValueError, match="HISTORICAL_SOURCE_UNAVAILABLE"):
        Harness(tmp_path).run_api_scenario(_command("trial-unpublished"))

    manifest = json.loads(
        (root / "executions" / "trial-unpublished" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "preflight_failed"
    assert requests_seen == []


def test_request_phase_crash_is_indeterminate_and_not_replayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path, with_cleanup=True)
    key = FilesystemLocalConfigLoader(tmp_path).load_required().runtime.cleanup_journal_key
    request_calls = 0

    def crash(_method: str, _url: str, **_kwargs: object) -> object:
        nonlocal request_calls
        request_calls += 1
        journal_path = root / "executions" / "trial-crash" / ".cleanup-journal.enc"
        journal = EncryptedCleanupJournal.load(journal_path, key=key)
        assert journal.summary().counts.armed == 1
        assert journal.summary().counts.pending == 0
        raise KeyboardInterrupt("simulated process kill after mutation send began")

    monkeypatch.setattr("requests.request", crash)
    harness = Harness(tmp_path)
    with pytest.raises(KeyboardInterrupt, match="simulated process kill"):
        harness.run_api_scenario(_command("trial-crash"))

    execution_root = root / "executions" / "trial-crash"
    manifest_path = execution_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "cleanup_indeterminate"
    assert manifest["error_kind"] == "KeyboardInterrupt"
    journal = EncryptedCleanupJournal.load(execution_root / ".cleanup-journal.enc", key=key)
    assert journal.summary().status == "indeterminate"
    assert journal.summary().counts.armed == 1
    obligation = journal.payload["obligations"][0]
    assert obligation["state"] == "armed"
    assert obligation["mutation_may_happen"] is True
    assert obligation["request_operation"] == "POST /orders"

    recovery = harness.resume_api_cleanup(
        ResumeApiCleanupCommand(
            workspace_id="demo",
            execution_id="trial-crash",
            environment="qa",
        )
    )
    assert recovery.status == "indeterminate"
    with pytest.raises(FileExistsError, match="will not be replayed"):
        harness.run_api_scenario(_command("trial-crash"))
    assert request_calls == 1


def test_leftover_started_manifest_becomes_indeterminate(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    execution_root = root / "executions" / "trial-interrupted"
    execution_root.mkdir(parents=True)
    manifest_path = execution_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "agentic-qa.harness.api-execution-manifest.v1",
                "workspace_id": "demo",
                "execution_id": "trial-interrupted",
                "environment": "qa",
                "status": "started",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError, match="will not be replayed"):
        Harness(tmp_path).run_api_scenario(_command("trial-interrupted"))

    assert json.loads(manifest_path.read_text(encoding="utf-8"))["status"] == "indeterminate"


def _recovery_journal(
    tmp_path: Path, execution_id: str
) -> tuple[Path, str, EncryptedCleanupJournal, ApiTestCasesDraft, Path]:
    root = _workspace(tmp_path)
    key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    local_path = tmp_path / "agentic-qa.local.yml"
    local = yaml.safe_load(local_path.read_text(encoding="utf-8"))
    local["secrets"]["values"]["runtime.cleanup_journal_key"] = key
    environment = local["api"]["services"]["demo"]["environments"]["qa"]
    environment["allowed_http_methods"] = ["POST", "DELETE"]
    local_path.write_text(yaml.safe_dump(local, sort_keys=False), encoding="utf-8")

    loader = FilesystemLocalConfigLoader(tmp_path)
    project = loader.resolve_api_project(loader.load_required(), "demo", "qa")
    workspace_config_path = root / "workspace.yml"
    workspace_config = yaml.safe_load(workspace_config_path.read_text(encoding="utf-8"))
    workspace_config["execution"]["environments"]["qa"] = project.policy.model_dump(
        mode="json", exclude_none=True
    )
    workspace_config["api_project"]["structural_sha256"] = project.structural_sha256
    workspace_config_path.write_text(
        yaml.safe_dump(workspace_config, sort_keys=False),
        encoding="utf-8",
    )

    execution_root = root / "executions" / execution_id
    execution_root.mkdir(parents=True)
    published = root / "published" / "api_test_draft" / "current.yml"
    source_sha256 = hashlib.sha256(published.read_bytes()).hexdigest()
    published_draft = ApiTestCasesDraft.model_validate(
        yaml.safe_load(published.read_text(encoding="utf-8"))
    )
    profile = Harness(tmp_path).api_execution_profile("demo", "qa")
    plan = build_api_execution_plan(
        workspace_id="demo",
        execution_id=execution_id,
        service="demo",
        environment="qa",
        source_cases_path="published/api_test_draft/current.yml",
        source_cases_sha256=source_sha256,
        source_publication_id="published-v1",
        source_history_path="published/api_test_draft/history/published-v1.yml",
        structural_sha256=project.structural_sha256,
        policy_sha256=project.policy_sha256,
        profile=profile,
        authentication=project.policy.api_auth,
        isolation=project.policy.isolation,
        operation_policies=project.policy.operation_policies,
        cases=list(published_draft.cases),
    )
    plan_path = execution_root / "execution-plan.json"
    plan_text = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    plan_path.write_text(plan_text, encoding="utf-8")
    (execution_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "agentic-qa.harness.api-execution-manifest.v2",
                "workspace_id": "demo",
                "execution_id": execution_id,
                "environment": "qa",
                "status": "indeterminate",
                "execution_plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    journal = EncryptedCleanupJournal(
        execution_root / ".cleanup-journal.enc",
        key=key,
        workspace_id="demo",
        execution_id=execution_id,
        environment="qa",
        source_cases_sha256=source_sha256,
        source_publication_id="published-v1",
        source_history_path="published/api_test_draft/history/published-v1.yml",
        structural_sha256=project.structural_sha256,
        policy_sha256=project.policy_sha256,
        execution_plan_sha256=plan.plan_sha256,
    )
    return root, key, journal, published_draft, execution_root


def _cleanup_step(identifier: str, path: str) -> ApiCleanupStep:
    return ApiCleanupStep.model_validate(
        {
            "id": identifier,
            "request": {"method": "DELETE", "path": path},
            "assertions": [{"type": "status_code", "expected": 204}],
        }
    )


def test_explicit_cleanup_resume_executes_only_pending_obligation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, key, journal, published_draft, execution_root = _recovery_journal(
        tmp_path, "cleanup-recovery"
    )
    journal.register(
        case_id="api-order-create",
        title="create order",
        cleanup=_cleanup_step("delete-order", "/orders/recovery-id"),
        runtime_variables={},
    )
    v2_payload = published_draft.model_dump(mode="json")
    v2_payload["cases"][0]["title"] = "renamed in v2"
    _publish_version(root, ApiTestCasesDraft.model_validate(v2_payload), "published-v2")
    calls: list[tuple[str, str]] = []

    def request(method: str, url: str, **_kwargs: object) -> _Response:
        calls.append((method, url))
        return _Response(204, url)

    monkeypatch.setattr("requests.request", request)
    result = Harness(tmp_path).resume_api_cleanup(
        ResumeApiCleanupCommand(
            workspace_id="demo",
            execution_id="cleanup-recovery",
            environment="qa",
        )
    )

    assert result.status == "complete"
    assert calls == [("DELETE", "https://qa.example.test/orders/recovery-id")]
    second = EncryptedCleanupJournal.load(execution_root / ".cleanup-journal.enc", key=key)
    assert second.summary().counts.completed == 1
    repeated = Harness(tmp_path).resume_api_cleanup(
        ResumeApiCleanupCommand(
            workspace_id="demo",
            execution_id="cleanup-recovery",
            environment="qa",
        )
    )
    assert repeated.status == "complete"
    assert len(calls) == 1

    (root / "published" / "api_test_draft" / "history" / "published-v1.yml").write_text(
        "tampered: true\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="HISTORICAL_SOURCE_UNAVAILABLE"):
        Harness(tmp_path).resume_api_cleanup(
            ResumeApiCleanupCommand(
                workspace_id="demo",
                execution_id="cleanup-recovery",
                environment="qa",
            )
        )
    assert len(calls) == 1


def test_cleanup_resume_executes_pending_when_another_obligation_is_armed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, _key, journal, _draft, _execution_root = _recovery_journal(tmp_path, "mixed-armed")
    journal.register(
        case_id="pending-case",
        title="pending",
        cleanup=_cleanup_step("delete-pending", "/orders/pending"),
        runtime_variables={},
    )
    journal.arm(
        case_id="armed-case",
        title="armed",
        cleanup=_cleanup_step("delete-armed", "/orders/armed"),
        runtime_variables={},
        request_operation="POST /orders",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        "requests.request",
        lambda method, url, **kwargs: (calls.append(url), _Response(204, url))[1],
    )

    result = Harness(tmp_path).resume_api_cleanup(
        ResumeApiCleanupCommand(workspace_id="demo", execution_id="mixed-armed", environment="qa")
    )

    assert calls == ["https://qa.example.test/orders/pending"]
    assert result.status == "indeterminate"
    assert result.summary.counts.completed == 1
    assert result.summary.counts.armed == 1


def test_cleanup_resume_executes_pending_when_another_obligation_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, _key, journal, _draft, _execution_root = _recovery_journal(tmp_path, "mixed-failed")
    failed_id = journal.register(
        case_id="failed-case",
        title="failed",
        cleanup=_cleanup_step("delete-failed", "/orders/failed"),
        runtime_variables={},
    )
    journal.before(failed_id)
    journal.after(failed_id, status="failed", request_sent=True)
    journal.register(
        case_id="pending-case",
        title="pending",
        cleanup=_cleanup_step("delete-pending", "/orders/pending"),
        runtime_variables={},
    )
    calls: list[str] = []
    monkeypatch.setattr(
        "requests.request",
        lambda method, url, **kwargs: (calls.append(url), _Response(204, url))[1],
    )

    result = Harness(tmp_path).resume_api_cleanup(
        ResumeApiCleanupCommand(workspace_id="demo", execution_id="mixed-failed", environment="qa")
    )

    assert calls == ["https://qa.example.test/orders/pending"]
    assert result.status == "failed"
    assert result.summary.counts.completed == 1
    assert result.summary.counts.failed == 1


def test_cleanup_resume_requires_manual_reapproval_after_policy_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, _key, journal, _draft, execution_root = _recovery_journal(tmp_path, "policy-change")
    journal.register(
        case_id="pending-case",
        title="pending",
        cleanup=_cleanup_step("delete-pending", "/orders/pending"),
        runtime_variables={},
    )
    local_path = tmp_path / "agentic-qa.local.yml"
    local = yaml.safe_load(local_path.read_text(encoding="utf-8"))
    local["api"]["services"]["demo"]["environments"]["qa"]["allowed_http_methods"].append("PATCH")
    local_path.write_text(yaml.safe_dump(local, sort_keys=False), encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: calls.append(url))

    result = Harness(tmp_path).resume_api_cleanup(
        ResumeApiCleanupCommand(workspace_id="demo", execution_id="policy-change", environment="qa")
    )

    assert result.status == "manual_reapproval_required"
    assert result.reason == "SAFETY_POLICY_CHANGED"
    assert result.original_policy_sha256 != result.current_policy_sha256
    assert calls == []
    events = (execution_root / "execution-events.jsonl").read_text(encoding="utf-8")
    assert '"event_type":"cleanup.manual_review_required"' in events
    manifest = json.loads((execution_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cleanup_recovery"]["status"] == "manual_reapproval_required"


def test_cleanup_resume_allows_credential_rotation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root, _key, journal, _draft, _execution_root = _recovery_journal(tmp_path, "credential-change")
    journal.register(
        case_id="pending-case",
        title="pending",
        cleanup=_cleanup_step("delete-pending", "/orders/pending"),
        runtime_variables={},
    )
    local_path = tmp_path / "agentic-qa.local.yml"
    local = yaml.safe_load(local_path.read_text(encoding="utf-8"))
    local["secrets"]["values"]["api.demo.qa.auth.fallback_token"] = "rotated-token"
    local_path.write_text(yaml.safe_dump(local, sort_keys=False), encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(
        "requests.request",
        lambda method, url, **kwargs: (calls.append(url), _Response(204, url))[1],
    )

    result = Harness(tmp_path).resume_api_cleanup(
        ResumeApiCleanupCommand(
            workspace_id="demo",
            execution_id="credential-change",
            environment="qa",
        )
    )

    assert result.status == "complete"
    assert calls == ["https://qa.example.test/orders/pending"]


def test_explicit_allure_failure_does_not_change_execution_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))
    harness = Harness(tmp_path)
    harness.run_api_scenario(_command("explicit-report-failure"))
    monkeypatch.setattr(
        "harness.infrastructure.api_scenario_run.generate_allure_html",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("plugin failed")),
    )

    result = harness.generate_api_allure_report(
        GenerateApiAllureReportCommand(
            workspace_id="demo",
            execution_id="explicit-report-failure",
        )
    )

    assert result.schema_version == "agentic-qa.harness.generate-api-allure-report-result.v2"
    assert result.status == "failed"
    assert result.error_kind == "RuntimeError"
    execution_root = root / "executions" / "explicit-report-failure"
    manifest = json.loads((execution_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["execution_status"] == "completed"
    assert manifest["test_result"] == "passed"
    assert manifest["cleanup_status"] == "not_required"
    assert manifest["report_status"] == "failed"
    event_types = [
        json.loads(line)["event_type"]
        for line in (execution_root / "execution-events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert event_types[-2:] == ["report.started", "report.finished"]


def test_allure_rebuild_uses_execution_historical_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))
    harness = Harness(tmp_path)
    harness.run_api_scenario(_command("historical-report"))
    execution_root = root / "executions" / "historical-report"

    v1 = ApiTestCasesDraft.model_validate(
        yaml.safe_load(
            (root / "published" / "api_test_draft" / "history" / "published-v1.yml").read_text(
                encoding="utf-8"
            )
        )
    )
    v2_payload = v1.model_dump(mode="json")
    v2_payload["cases"][0]["title"] = "v2 title must not appear"
    v2_payload["cases"][0]["priority"] = "P0"
    _publish_version(root, ApiTestCasesDraft.model_validate(v2_payload), "published-v2")
    shutil.rmtree(execution_root / "allure-results")
    (execution_root / "report-summary.json").unlink()

    harness.generate_api_allure_report(
        GenerateApiAllureReportCommand(
            workspace_id="demo",
            execution_id="historical-report",
        )
    )

    report = json.loads((execution_root / "report-summary.json").read_text(encoding="utf-8"))
    assert report["cases"][0]["title"] == "create order"
    result_file = next((execution_root / "allure-results").glob("*-result.json"))
    allure = json.loads(result_file.read_text(encoding="utf-8"))
    assert allure["name"].endswith("create order")
    assert "v2 title must not appear" not in json.dumps(allure)


def test_allure_rebuild_uses_execution_plan_service_after_workspace_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))
    harness = Harness(tmp_path)
    harness.run_api_scenario(_command("service-drift"))
    execution_root = root / "executions" / "service-drift"
    workspace_path = root / "workspace.yml"
    workspace = yaml.safe_load(workspace_path.read_text(encoding="utf-8"))
    workspace["api_project"]["service"] = "service-B"
    workspace_path.write_text(yaml.safe_dump(workspace, sort_keys=False), encoding="utf-8")
    shutil.rmtree(execution_root / "allure-results")
    (execution_root / "report-summary.json").unlink()

    harness.generate_api_allure_report(
        GenerateApiAllureReportCommand(workspace_id="demo", execution_id="service-drift")
    )

    result_file = next((execution_root / "allure-results").glob("*-result.json"))
    allure = json.loads(result_file.read_text(encoding="utf-8"))
    assert {item["value"] for item in allure["labels"] if item["name"] == "parentSuite"} == {"demo"}
    assert "service-B" not in json.dumps(allure)


def test_allure_rebuild_rejects_manifest_source_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))
    harness = Harness(tmp_path)
    harness.run_api_scenario(_command("manifest-source-drift"))
    manifest_path = root / "executions" / "manifest-source-drift" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_history_path"] = "published/api_test_draft/history/published-v2.yml"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ExecutionSourceLinkageError, match="EXECUTION_SOURCE_LINKAGE_MISMATCH"):
        harness.generate_api_allure_report(
            GenerateApiAllureReportCommand(
                workspace_id="demo", execution_id="manifest-source-drift"
            )
        )


def test_allure_rebuild_rejects_execution_plan_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))
    harness = Harness(tmp_path)
    harness.run_api_scenario(_command("plan-tamper"))
    plan_path = root / "executions" / "plan-tamper" / "execution-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["service"] = "tampered-service"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ExecutionPlanTamperedError, match="EXECUTION_PLAN_TAMPERED"):
        harness.generate_api_allure_report(
            GenerateApiAllureReportCommand(workspace_id="demo", execution_id="plan-tamper")
        )


def test_allure_rebuild_resolves_legacy_plan_v1_by_unique_source_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: _Response(201, url))
    harness = Harness(tmp_path)
    harness.run_api_scenario(_command("legacy-plan"))
    execution_root = root / "executions" / "legacy-plan"
    plan_path = execution_root / "execution-plan.json"
    manifest_path = execution_root / "manifest.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["schema_version"] = "agentic-qa.api-execution-plan.v1"
    plan.pop("source_publication_id")
    plan.pop("source_history_path")
    plan.pop("policy_sha256")
    semantic = json.dumps(
        {key: value for key, value in plan.items() if key != "plan_sha256"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    plan["plan_sha256"] = hashlib.sha256(semantic).hexdigest()
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["execution_plan_sha256"] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    shutil.rmtree(execution_root / "allure-results")
    (execution_root / "report-summary.json").unlink()

    result = harness.generate_api_allure_report(
        GenerateApiAllureReportCommand(workspace_id="demo", execution_id="legacy-plan")
    )

    assert result.status in {"generated", "results_only"}
    assert list((execution_root / "allure-results").glob("*-result.json"))
