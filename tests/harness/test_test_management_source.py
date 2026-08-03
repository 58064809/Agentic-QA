from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from harness import CreateWorkspaceCommand, Harness, StartRunCommand
from harness.budget import Budget
from harness.contracts import ExecutionProfile
from harness.infrastructure.manifests.registry import AgentRegistry, SkillRegistry, ToolRegistry
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.tools import runtime as runtime_module
from harness.infrastructure.tools.runtime import ToolRuntime
from harness.infrastructure.tools.test_management import QaseSourceConfig, read_qase, read_testrail
from harness.infrastructure.tools.test_management import QaseTestManagementQuery as QaseQuery
from harness.infrastructure.tools.test_management import TestManagementQuery as ManagementQuery
from harness.infrastructure.tools.test_management import TestRailSourceConfig as RailSourceConfig
from harness.testing.evals import recorded_model_gateway


class FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = json.dumps(payload).encode()
        self.status_code = status_code
        self.headers = headers or {}

    def iter_content(self, chunk_size: int):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def _config() -> RailSourceConfig:
    return RailSourceConfig(
        base_url_env="TESTRAIL_URL",
        username_env="TESTRAIL_USER",
        api_key_env="TESTRAIL_API_KEY",
        max_items=20,
    )


def _env() -> dict[str, str]:
    return {
        "TESTRAIL_URL": "https://qa.testrail.example/team",
        "TESTRAIL_USER": "qa@example.test",
        "TESTRAIL_API_KEY": "not-a-real-api-key",
    }


def _qase_config() -> QaseSourceConfig:
    return QaseSourceConfig(
        base_url_env="QASE_URL",
        api_token_env="QASE_API_TOKEN",
        max_items=20,
    )


def _qase_env() -> dict[str, str]:
    return {
        "QASE_URL": "https://api.qase.io",
        "QASE_API_TOKEN": "not-a-real-qase-token",
    }


def test_testrail_list_cases_uses_fixed_read_only_endpoint_and_bounds_page() -> None:
    response = FakeResponse(
        {
            "offset": 10,
            "limit": 2,
            "size": 2,
            "_links": {"next": "/api/v2/get_cases/7&limit=2&offset=12"},
            "cases": [
                {"id": 101, "title": "login succeeds"},
                {"id": 102, "title": "login rejects invalid password"},
            ],
        }
    )
    session = FakeSession(response)

    result = read_testrail(
        _config(),
        ManagementQuery(
            operation="list_cases",
            project_id=7,
            suite_id=8,
            section_id=9,
            limit=2,
            offset=10,
        ),
        env=_env(),
        session=session,  # type: ignore[arg-type]
    )

    assert session.calls == [
        {
            "url": "https://qa.testrail.example/team/index.php?/api/v2/get_cases/7",
            "params": {"suite_id": 8, "section_id": 9, "limit": 2, "offset": 10},
            "headers": {"Accept": "application/json"},
            "auth": ("qa@example.test", "not-a-real-api-key"),
            "timeout": 10,
            "allow_redirects": False,
            "stream": True,
        }
    ]
    assert result["source"] == {
        "origin": "https://qa.testrail.example",
        "resource": "get_cases/7",
    }
    assert [item["id"] for item in result["records"]] == [101, 102]
    assert result["pagination"] == {
        "offset": 10,
        "limit": 2,
        "returned": 2,
        "next_offset": 12,
        "truncated": True,
    }


def test_qase_list_cases_uses_fixed_read_only_endpoint_and_bounds_page() -> None:
    response = FakeResponse(
        {
            "status": True,
            "result": {
                "total": 12,
                "filtered": 12,
                "count": 2,
                "entities": [
                    {"id": 101, "title": "login succeeds"},
                    {"id": 102, "title": "login rejects invalid password"},
                ],
            },
        }
    )
    session = FakeSession(response)

    result = read_qase(
        _qase_config(),
        QaseQuery(
            operation="list_cases",
            project_code="AUTH",
            suite_id=8,
            limit=2,
            offset=10,
        ),
        env=_qase_env(),
        session=session,  # type: ignore[arg-type]
    )

    assert session.calls == [
        {
            "url": "https://api.qase.io/v1/case/AUTH",
            "params": {"suite_id": 8, "limit": 2, "offset": 10},
            "headers": {
                "Accept": "application/json",
                "Token": "not-a-real-qase-token",
            },
            "timeout": 10,
            "allow_redirects": False,
            "stream": True,
        }
    ]
    assert result["provider"] == "qase"
    assert result["source"] == {
        "origin": "https://api.qase.io",
        "resource": "case/AUTH",
    }
    assert [item["id"] for item in result["records"]] == [101, 102]
    assert result["pagination"] == {
        "offset": 10,
        "limit": 2,
        "returned": 2,
        "next_offset": None,
        "truncated": False,
    }


def test_qase_get_case_normalizes_single_result() -> None:
    session = FakeSession(
        FakeResponse(
            {
                "status": True,
                "result": {"id": 17, "title": "password reset succeeds"},
            }
        )
    )

    result = read_qase(
        _qase_config(),
        QaseQuery(operation="get_case", project_code="AUTH", case_id=17),
        env=_qase_env(),
        session=session,  # type: ignore[arg-type]
    )

    assert session.calls[0]["url"] == "https://api.qase.io/v1/case/AUTH/17"
    assert session.calls[0]["params"] == {}
    assert result["records"] == [{"id": 17, "title": "password reset succeeds"}]
    assert result["pagination"]["next_offset"] is None


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"operation": "get_case"}, "requires arguments"),
        ({"operation": "list_projects", "project_id": 1}, "does not accept"),
    ],
)
def test_testrail_query_rejects_missing_or_unexpected_identifiers(
    payload: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        ManagementQuery.model_validate(payload)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"operation": "get_case", "project_code": "AUTH"}, "requires arguments"),
        ({"operation": "list_projects", "project_code": "AUTH"}, "does not accept"),
        ({"operation": "list_sections"}, "does not support"),
        ({"operation": "list_cases", "project_code": "../outside"}, "string_pattern_mismatch"),
    ],
)
def test_qase_query_rejects_missing_unsupported_or_unsafe_identifiers(
    payload: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        QaseQuery.model_validate(payload)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://testrail.example",
        "https://user:password@testrail.example",
        "https://testrail.example?redirect=https://outside.example",
    ],
)
def test_testrail_config_rejects_unsafe_base_urls(base_url: str) -> None:
    env = {**_env(), "TESTRAIL_URL": base_url}
    with pytest.raises(ValueError, match="HTTPS URL"):
        _config().credentials(env)


def test_testrail_rejects_redirects_and_oversized_responses() -> None:
    redirect = FakeSession(FakeResponse({}, status_code=302))
    with pytest.raises(RuntimeError, match="redirect"):
        read_testrail(
            _config(),
            ManagementQuery(operation="list_projects"),
            env=_env(),
            session=redirect,  # type: ignore[arg-type]
        )

    oversized = FakeSession(
        FakeResponse([], headers={"Content-Length": str(_config().max_response_bytes + 1)})
    )
    with pytest.raises(RuntimeError, match="max_response_bytes"):
        read_testrail(
            _config(),
            ManagementQuery(operation="list_projects"),
            env=_env(),
            session=oversized,  # type: ignore[arg-type]
        )


def test_qase_rejects_redirects_and_unsuccessful_payloads() -> None:
    redirect = FakeSession(FakeResponse({}, status_code=302))
    with pytest.raises(RuntimeError, match="redirect"):
        read_qase(
            _qase_config(),
            QaseQuery(operation="list_projects"),
            env=_qase_env(),
            session=redirect,  # type: ignore[arg-type]
        )

    unsuccessful = FakeSession(FakeResponse({"status": False, "result": None}))
    with pytest.raises(RuntimeError, match="status is not successful"):
        read_qase(
            _qase_config(),
            QaseQuery(operation="list_projects"),
            env=_qase_env(),
            session=unsuccessful,  # type: ignore[arg-type]
        )


def test_tool_runtime_reads_config_in_analysis_only_and_redacts_external_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(tmp_path, model_gateway=recorded_model_gateway())
    workspace = harness.create_workspace(CreateWorkspaceCommand(workspace_id="demo"))
    config_path = workspace / "workspace.yml"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    payload["data_sources"] = {
        "test_management": {
            "provider": "testrail",
            "schema_version": "agentic-qa.harness.testrail-source.v1",
            "base_url_env": "TESTRAIL_URL",
            "username_env": "TESTRAIL_USER",
            "api_key_env": "TESTRAIL_API_KEY",
        }
    }
    config_path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test"))
    captured: list[tuple[RailSourceConfig, ManagementQuery]] = []

    def fake_read(
        config: RailSourceConfig,
        query: ManagementQuery,
    ) -> dict[str, object]:
        captured.append((config, query))
        return {
            "schema_version": "agentic-qa.harness.test-management-result.v1",
            "provider": "testrail",
            "operation": "get_case",
            "source": {"origin": "https://qa.example", "resource": "get_case/3"},
            "records": [{"id": 3, "api_key": "must-not-survive"}],
            "pagination": {
                "offset": 0,
                "limit": 100,
                "returned": 1,
                "next_offset": None,
                "truncated": False,
            },
        }

    monkeypatch.setattr(runtime_module, "read_testrail", fake_read)
    store = FilesystemStore(tmp_path)
    tools = ToolRegistry.builtin()
    skills = SkillRegistry.builtin()
    agents = AgentRegistry.builtin(skills=skills, tools=tools)
    runtime = ToolRuntime(store=store, agents=agents, tools=tools, budget=Budget())

    result = runtime.call(
        workspace="demo",
        run_id=snapshot.run_id,
        agent="requirement_analyst",
        tool="test_management.read",
        arguments={"operation": "get_case", "case_id": 3},
        profile=ExecutionProfile(),
        idempotency_key="case-3",
    )

    assert captured[0][1].case_id == 3
    assert result["records"][0]["api_key"] == "<redacted>"
    record = next(
        item
        for item in (workspace / "runs" / snapshot.run_id / "tool-calls").glob("*.json")
        if json.loads(item.read_text(encoding="utf-8")).get("tool") == "test_management.read"
    )
    assert "must-not-survive" not in record.read_text(encoding="utf-8")


def test_tool_runtime_dispatches_qase_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(tmp_path, model_gateway=recorded_model_gateway())
    workspace = harness.create_workspace(CreateWorkspaceCommand(workspace_id="demo"))
    config_path = workspace / "workspace.yml"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    payload["data_sources"] = {
        "test_management": {
            "provider": "qase",
            "schema_version": "agentic-qa.harness.qase-source.v1",
            "base_url_env": "QASE_URL",
            "api_token_env": "QASE_API_TOKEN",
        }
    }
    config_path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test"))
    captured: list[tuple[QaseSourceConfig, QaseQuery]] = []

    def fake_read(
        config: QaseSourceConfig,
        query: QaseQuery,
    ) -> dict[str, object]:
        captured.append((config, query))
        return {
            "schema_version": "agentic-qa.harness.test-management-result.v1",
            "provider": "qase",
            "operation": "get_case",
            "source": {"origin": "https://api.qase.io", "resource": "case/AUTH/3"},
            "records": [{"id": 3}],
            "pagination": {
                "offset": 0,
                "limit": 100,
                "returned": 1,
                "next_offset": None,
                "truncated": False,
            },
        }

    monkeypatch.setattr(runtime_module, "read_qase", fake_read)
    store = FilesystemStore(tmp_path)
    tools = ToolRegistry.builtin()
    skills = SkillRegistry.builtin()
    agents = AgentRegistry.builtin(skills=skills, tools=tools)
    runtime = ToolRuntime(store=store, agents=agents, tools=tools, budget=Budget())

    result = runtime.call(
        workspace="demo",
        run_id=snapshot.run_id,
        agent="requirement_analyst",
        tool="test_management.read",
        arguments={"operation": "get_case", "project_code": "AUTH", "case_id": 3},
        profile=ExecutionProfile(),
        idempotency_key="qase-case-3",
    )

    assert captured[0][1].project_code == "AUTH"
    assert result["provider"] == "qase"


def test_test_management_tool_is_read_only_and_not_available_to_review_agent() -> None:
    tools = ToolRegistry.builtin()
    skills = SkillRegistry.builtin()
    agents = AgentRegistry.builtin(skills=skills, tools=tools)

    manifest = tools.get("test_management.read")
    assert manifest.risk.value == "read_only"
    assert "test_management.read" in agents.get("test_designer").tool_allowlist
    assert "test_management.read" not in agents.get("review_assistant").tool_allowlist
