from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest
import yaml

from harness import (
    CreateWorkspaceCommand,
    Harness,
    ResumeApiCleanupCommand,
    RunApiScenarioCommand,
)
from harness.domain.schemas.api_test_cases import ApiCleanupStep, ApiTestCasesDraft
from harness.infrastructure.api_automation import FilesystemApiAutomationService
from harness.infrastructure.api_cleanup_journal import EncryptedCleanupJournal
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


def _workspace(tmp_path: Path, *, expected_status: int = 201) -> Path:
    source = tmp_path / "local-sources" / "api" / "demo"
    source.mkdir(parents=True)
    local_config = {
        "schema_version": "agentic-qa.local-config.v1",
        "model": {
            "provider": "recorded",
            "api_key_env": "UNIT_MODEL_KEY",
            "flash_model": "recorded-flash",
            "pro_model": "recorded-pro",
            "base_url": "https://model.example.test",
        },
        "rag": {"provider": "local-lexical"},
        "postgres": {
            "host": "localhost",
            "port": 5432,
            "database": "postgres",
            "user": "postgres",
            "password": "unit-only",
        },
        "test_management": {"provider": "none"},
        "workspace_defaults": {},
        "api": {
            "services": {
                "demo": {
                    "source_directory": "local-sources/api/demo",
                    "environments": {
                        "qa": {
                            "base_url": "https://qa.example.test",
                            "trusted_origins": ["https://qa.example.test"],
                            "allowed_http_methods": ["POST"],
                            "cleanup_exempt_operations": ["POST /orders"],
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
            "schema_version": "agentic-qa.api-cases.v1.1",
            "artifact_type": "api_automation_cases",
            "status": "needs_human_review",
            "human_review_required": True,
            "base_url_env": "AGENTIC_QA_BASE_URL",
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
                    "variables": {"datasets": [], "extract": {}},
                    "cleanup": [],
                }
            ],
            "review_questions": ["Review before publication"],
        }
    )
    target = root / "published" / "api_test_draft" / "current.yml"
    target.parent.mkdir(parents=True)
    target.write_text(
        yaml.safe_dump(draft.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
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

    assert result.status == "passed"
    assert len(requests_seen) == 1
    assert requests_seen[0][2]["allow_redirects"] is False
    assert requests_seen[0][2]["timeout"] == 7
    execution_root = root / "executions" / "trial-001"
    manifest = json.loads((execution_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["result"] == "passed"
    assert manifest["source_cases_sha256"] == result.source_cases_sha256
    evidence = (execution_root / "evidence.json").read_text(encoding="utf-8")
    summary = (execution_root / "summary.md").read_text(encoding="utf-8")
    report_summary = json.loads(
        (execution_root / "report-summary.json").read_text(encoding="utf-8")
    )
    events = (execution_root / "execution-events.jsonl").read_text(encoding="utf-8")
    persisted = manifest | {"evidence": evidence, "summary_report": summary}
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

    with pytest.raises(ValueError, match="only accepts published"):
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
    root = _workspace(tmp_path)
    execute_calls = 0

    def crash(_service: FilesystemApiAutomationService, _command: object) -> object:
        nonlocal execute_calls
        execute_calls += 1
        raise RuntimeError("simulated uncertain transport interruption")

    monkeypatch.setattr(FilesystemApiAutomationService, "execute", crash)
    harness = Harness(tmp_path)
    with pytest.raises(RuntimeError, match="simulated uncertain"):
        harness.run_api_scenario(_command("trial-crash"))

    manifest_path = root / "executions" / "trial-crash" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "indeterminate"
    assert manifest["error_kind"] == "RuntimeError"
    with pytest.raises(FileExistsError, match="will not be replayed"):
        harness.run_api_scenario(_command("trial-crash"))
    assert execute_calls == 1


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


def test_explicit_cleanup_resume_executes_only_pending_obligation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    local_path = tmp_path / "agentic-qa.local.yml"
    local = yaml.safe_load(local_path.read_text(encoding="utf-8"))
    local["runtime"] = {"cleanup_journal_key": key}
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

    execution_root = root / "executions" / "cleanup-recovery"
    execution_root.mkdir(parents=True)
    published = root / "published" / "api_test_draft" / "current.yml"
    source_sha256 = hashlib.sha256(published.read_bytes()).hexdigest()
    (execution_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "agentic-qa.harness.api-execution-manifest.v2",
                "workspace_id": "demo",
                "execution_id": "cleanup-recovery",
                "environment": "qa",
                "status": "indeterminate",
            }
        ),
        encoding="utf-8",
    )
    journal = EncryptedCleanupJournal(
        execution_root / ".cleanup-journal.enc",
        key=key,
        workspace_id="demo",
        execution_id="cleanup-recovery",
        environment="qa",
        source_cases_sha256=source_sha256,
        structural_sha256=project.structural_sha256,
    )
    journal.register(
        case_id="api-order-create",
        title="create order",
        cleanup=ApiCleanupStep.model_validate(
            {
                "id": "delete-order",
                "request": {"method": "DELETE", "path": "/orders/recovery-id"},
                "assertions": [{"type": "status_code", "expected": 204}],
            }
        ),
        runtime_variables={},
    )
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
