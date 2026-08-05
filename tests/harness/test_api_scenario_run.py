from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from harness import CreateWorkspaceCommand, Harness, RunApiScenarioCommand
from harness.domain.schemas.api_test_cases import ApiTestCasesDraft
from harness.infrastructure.api_automation import FilesystemApiAutomationService


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
    harness = Harness(tmp_path)
    root = harness.create_workspace(CreateWorkspaceCommand(workspace_id="demo"))
    config_path = root / "workspace.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["execution"]["environments"]["qa"] = {
        "base_url_env": "AGENTIC_QA_BASE_URL",
        "trusted_origins": ["https://qa.example.test"],
        "allowed_http_methods": ["POST"],
        "max_request_timeout_seconds": 7,
        "api_auth": {
            "mode": "static_token",
            "token_env": "QA_API_TOKEN",
            "injection": {
                "location": "header",
                "name": "Authorization",
                "prefix": "Bearer",
            },
        },
    }
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    openapi_ref = {
        "source_type": "openapi",
        "source_path": "sources/openapi.yml",
        "chunk_id": "POST /orders",
        "locator": "paths./orders.post",
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
    monkeypatch.setenv("AGENTIC_QA_BASE_URL", "https://qa.example.test")
    monkeypatch.setenv("QA_API_TOKEN", "local-runtime-token")
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

    with pytest.raises(FileExistsError, match="will not be replayed"):
        harness.run_api_scenario(_command("trial-001"))
    assert len(requests_seen) == 1


def test_failed_assertion_is_persisted_as_failed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path, expected_status=200)
    monkeypatch.setenv("AGENTIC_QA_BASE_URL", "https://qa.example.test")
    monkeypatch.setenv("QA_API_TOKEN", "local-runtime-token")
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
    monkeypatch.delenv("AGENTIC_QA_BASE_URL", raising=False)
    monkeypatch.setenv("QA_API_TOKEN", "local-runtime-token")
    monkeypatch.setattr(
        "requests.request",
        lambda method, url, **kwargs: requests_seen.append(url),
    )

    harness = Harness(tmp_path)
    with pytest.raises(ValueError, match="base URL environment variable"):
        harness.run_api_scenario(_command("trial-preflight"))

    assert requests_seen == []
    manifest_path = root / "executions" / "trial-preflight" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "preflight_failed"
    assert manifest["error_kind"] == "ValueError"
    with pytest.raises(FileExistsError, match="will not be replayed"):
        harness.run_api_scenario(_command("trial-preflight"))
    assert requests_seen == []


def test_run_rejects_missing_published_yaml_without_sending_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    (root / "published" / "api_test_draft" / "current.yml").unlink()
    monkeypatch.setenv("AGENTIC_QA_BASE_URL", "https://qa.example.test")
    monkeypatch.setenv("QA_API_TOKEN", "local-runtime-token")
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
    monkeypatch.setenv("AGENTIC_QA_BASE_URL", "https://qa.example.test")
    monkeypatch.setenv("QA_API_TOKEN", "local-runtime-token")
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
