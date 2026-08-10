from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from harness import AgenticQaLocalConfig, CreateWorkspaceCommand, Harness, StartRunCommand
from harness.budget import Budget
from harness.contracts import ExecutionProfile
from harness.infrastructure.local_config import FilesystemLocalConfigLoader
from harness.infrastructure.manifests.registry import AgentRegistry, SkillRegistry, ToolRegistry
from harness.infrastructure.mcp.playwright import MCPBridge, MCPToolSnapshot
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.tools.runtime import ToolRuntime
from harness.testing.evals import recorded_model_gateway


def _runtime_dependencies(tmp_path: Path):
    store = FilesystemStore(tmp_path)
    tools = ToolRegistry.builtin()
    skills = SkillRegistry.builtin()
    agents = AgentRegistry.builtin(skills=skills, tools=tools)
    return store, agents, tools


def _started_run(tmp_path: Path, *, source_content: str | None = None):
    harness = Harness(tmp_path, model_gateway=recorded_model_gateway())
    workspace = harness.create_workspace(CreateWorkspaceCommand(workspace_id="demo"))
    if source_content is not None:
        (workspace / "sources/requirement.md").write_text(source_content, encoding="utf-8")
    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test"))
    return workspace, snapshot


def test_tool_allowlist_profile_and_idempotency(tmp_path: Path) -> None:
    _, snapshot = _started_run(tmp_path)
    store, agents, tools = _runtime_dependencies(tmp_path)
    calls = 0

    def execute(_arguments: dict[str, object]) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"calls": calls}

    runtime = ToolRuntime(
        store=store,
        agents=agents,
        tools=tools,
        budget=Budget(),
        handlers={"api.execute": execute},
    )
    with pytest.raises(PermissionError, match="explicit test environment"):
        runtime.call(
            workspace="demo",
            run_id=snapshot.run_id,
            agent="api_test_engineer",
            tool="api.execute",
            arguments={"cases_path": "published/api_test_draft/current.yml"},
            profile=ExecutionProfile(),
            idempotency_key="case-1",
        )

    profile = ExecutionProfile(environment="staging")
    first = runtime.call(
        workspace="demo",
        run_id=snapshot.run_id,
        agent="api_test_engineer",
        tool="api.execute",
        arguments={"cases_path": "published/api_test_draft/current.yml"},
        profile=profile,
        idempotency_key="case-1",
    )
    second = runtime.call(
        workspace="demo",
        run_id=snapshot.run_id,
        agent="api_test_engineer",
        tool="api.execute",
        arguments={"cases_path": "published/api_test_draft/current.yml"},
        profile=profile,
        idempotency_key="case-1",
    )
    assert first == second == {"calls": 1}

    with pytest.raises(PermissionError, match="not allowed"):
        runtime.call(
            workspace="demo",
            run_id=snapshot.run_id,
            agent="review_assistant",
            tool="artifact.promote",
            arguments={},
            profile=profile,
            idempotency_key="forbidden",
        )

    with pytest.raises(PermissionError, match="allow_ui_mutations"):
        runtime.call(
            workspace="demo",
            run_id=snapshot.run_id,
            agent="ui_test_engineer",
            tool="mcp.playwright",
            arguments={"tool": "browser_click", "arguments": {}},
            profile=profile,
            idempotency_key="ui-forbidden",
        )


def test_read_tool_result_is_reused_for_same_idempotency_key(tmp_path: Path) -> None:
    workspace, snapshot = _started_run(tmp_path, source_content="requirement")
    store, agents, tools = _runtime_dependencies(tmp_path)
    budget = Budget()
    events: list[dict[str, object]] = []
    runtime = ToolRuntime(
        store=store,
        agents=agents,
        tools=tools,
        budget=budget,
        on_call=events.append,
    )

    arguments = {"path": "sources/requirement.md"}
    first = runtime.call(
        workspace="demo",
        run_id=snapshot.run_id,
        agent="requirement_analyst",
        tool="workspace.read",
        arguments=arguments,
        profile=ExecutionProfile(),
        idempotency_key="same-read",
    )
    second = runtime.call(
        workspace="demo",
        run_id=snapshot.run_id,
        agent="requirement_analyst",
        tool="workspace.read",
        arguments=arguments,
        profile=ExecutionProfile(),
        idempotency_key="same-read",
    )

    assert first == second
    assert budget.snapshot().tool_calls == 1
    assert len(events) == 1


def test_model_only_sees_run_frozen_mcp_tools(tmp_path: Path) -> None:
    harness = Harness(tmp_path, model_gateway=recorded_model_gateway())
    harness.create_workspace(CreateWorkspaceCommand(workspace_id="demo"))
    store, agents, tools = _runtime_dependencies(tmp_path)
    runtime_without_mcp = ToolRuntime(
        store=store,
        agents=agents,
        tools=tools,
        budget=Budget(),
    )

    assert [
        item["name"]
        for item in runtime_without_mcp.model_tools(agents.get("ui_test_engineer").tool_allowlist)
    ] == ["workspace.read"]

    bridge = MCPBridge(
        MCPToolSnapshot.freeze(
            server="playwright",
            transport="stdio",
            listed_tools=[
                {
                    "name": "browser_snapshot",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
                {"name": "browser_click", "inputSchema": {"type": "object"}},
            ],
            allowlist={"browser_snapshot"},
        ),
        lambda _name, _arguments: {},
    )
    runtime = ToolRuntime(
        store=store,
        agents=agents,
        tools=tools,
        budget=Budget(),
        handlers={"mcp.playwright": bridge.tool_handler},
    )

    visible = runtime.model_tools(agents.get("ui_test_engineer").tool_allowlist)
    mcp = next(item for item in visible if item["name"] == "mcp.playwright.browser_snapshot")
    assert mcp["input_schema"]["additionalProperties"] is False


def test_live_capture_facade_hides_raw_network_tools_and_enforces_origin(
    tmp_path: Path,
) -> None:
    workspace, snapshot = _started_run(tmp_path)
    source = tmp_path / "local-sources" / "api" / "ui"
    source.mkdir(parents=True)
    local_config = AgenticQaLocalConfig.model_validate(
        {
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
                    "ui": {
                        "source_directory": "local-sources/api/ui",
                        "environments": {
                            "qa": {
                                "base_url": "https://qa.example.test/app",
                                "trusted_origins": ["https://qa.example.test"],
                                "allowed_http_methods": ["GET", "HEAD", "OPTIONS"],
                                "auth": {"fallback_token": "unit-token"},
                            }
                        },
                    }
                }
            },
        }
    )
    project = FilesystemLocalConfigLoader(tmp_path).resolve_api_project(local_config, "ui", "qa")
    config = yaml.safe_load((workspace / "workspace.yml").read_text(encoding="utf-8"))
    policy = project.policy.model_copy(update={"allow_ui_mutations": True})
    config["execution"]["environments"]["qa"] = policy.model_dump(mode="json", exclude_none=True)
    (workspace / "workspace.yml").write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )
    store, agents, tools = _runtime_dependencies(tmp_path)
    document_origin = "https://qa.example.test"
    page_origin = "https://qa.example.test"

    def caller(name: str, arguments: dict[str, object]) -> dict[str, object]:
        if name == "browser_network_requests":
            text = f"### Result\n1. [GET] {document_origin}/api/health => [200]"
        elif name == "browser_network_request" and "part" not in arguments:
            text = (
                f"### Result\n#1 [GET] {document_origin}/api/health\n\n"
                "  General\n"
                "    status: [200]\n"
                "    duration: 8ms\n"
                "    type: document\n"
                "    mimeType: application/json\n\n"
                "  Response headers\n"
                "    content-type: application/json\n"
            )
        elif name == "browser_network_request":
            text = '### Result\n{"ok":true}'
        else:
            text = f"### Result\nnavigated\n### Page\n- Page URL: {page_origin}/app"
        return {"content": [{"type": "text", "text": text}], "isError": False}

    listed_tools = [
        {
            "name": "browser_navigate",
            "inputSchema": {
                "type": "object",
                "required": ["url"],
                "properties": {"url": {"type": "string"}},
                "additionalProperties": False,
            },
        },
        {
            "name": "browser_network_requests",
            "inputSchema": {
                "type": "object",
                "required": ["static"],
                "properties": {"static": {"type": "boolean"}},
                "additionalProperties": False,
            },
        },
        {
            "name": "browser_network_request",
            "inputSchema": {
                "type": "object",
                "required": ["index"],
                "properties": {
                    "index": {"type": "integer"},
                    "part": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    ]
    bridge = MCPBridge(
        MCPToolSnapshot.freeze(
            server="playwright",
            transport="stdio",
            listed_tools=listed_tools,
            allowlist={item["name"] for item in listed_tools},
        ),
        caller,
    )
    runtime = ToolRuntime(
        store=store,
        agents=agents,
        tools=tools,
        budget=Budget(),
        handlers={"mcp.playwright": bridge.tool_handler},
        local_config=local_config,
    )
    profile = ExecutionProfile(
        environment="qa",
        base_url_env="LOCAL_UI_QA_BASE_URL",
        allow_ui_mutations=True,
    )

    visible = runtime.model_tools(agents.get("api_test_engineer").tool_allowlist)
    projected_subtools = {
        item["name"].removeprefix("mcp.playwright.")
        for item in visible
        if item["name"].startswith("mcp.playwright.")
    }
    assert projected_subtools == {"browser_navigate"}
    assert "network.capture.live" in {item["name"] for item in visible}

    with pytest.raises(PermissionError, match="only available through"):
        runtime.call(
            workspace="demo",
            run_id=snapshot.run_id,
            agent="api_test_engineer",
            tool="mcp.playwright",
            arguments={"tool": "browser_network_requests", "arguments": {"static": False}},
            profile=profile,
            idempotency_key="raw-network",
        )
    with pytest.raises(PermissionError, match="must match"):
        runtime.call(
            workspace="demo",
            run_id=snapshot.run_id,
            agent="api_test_engineer",
            tool="mcp.playwright",
            arguments={
                "tool": "browser_navigate",
                "arguments": {"url": "https://outside.example.test"},
            },
            profile=profile,
            idempotency_key="outside-origin",
        )

    page_origin = "https://outside.example.test"
    with pytest.raises(PermissionError, match="page left"):
        runtime.call(
            workspace="demo",
            run_id=snapshot.run_id,
            agent="api_test_engineer",
            tool="mcp.playwright",
            arguments={
                "tool": "browser_navigate",
                "arguments": {"url": "https://qa.example.test/app"},
            },
            profile=profile,
            idempotency_key="redirected-navigation",
        )
    page_origin = "https://qa.example.test"

    result = runtime.call(
        workspace="demo",
        run_id=snapshot.run_id,
        agent="api_test_engineer",
        tool="network.capture.live",
        arguments={"max_requests": 25},
        profile=profile,
        idempotency_key="live-capture",
    )
    assert result["capture_format"] == "playwright_mcp"
    assert result["candidates"][0]["origin"] == "https://qa.example.test"

    document_origin = "https://outside.example.test"
    with pytest.raises(PermissionError, match="left the configured test origin"):
        runtime.call(
            workspace="demo",
            run_id=snapshot.run_id,
            agent="api_test_engineer",
            tool="network.capture.live",
            arguments={"max_requests": 25},
            profile=profile,
            idempotency_key="redirected-capture",
        )
