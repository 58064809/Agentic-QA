from __future__ import annotations

from pathlib import Path

import pytest

from harness import Harness, TaskRequest
from harness.budget import Budget
from harness.contracts import ExecutionProfile
from harness.evals import recorded_model_gateway
from harness.mcp import MCPBridge, MCPToolSnapshot
from harness.tools import ToolRuntime


def test_tool_allowlist_profile_and_idempotency(tmp_path: Path) -> None:
    harness = Harness(tmp_path, model_gateway=recorded_model_gateway())
    harness.init_workspace("demo")
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test"))
    calls = 0

    def execute(_arguments: dict[str, object]) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"calls": calls}

    runtime = ToolRuntime(
        store=harness.store,
        agents=harness.agents,
        tools=harness.tools,
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
    harness = Harness(tmp_path, model_gateway=recorded_model_gateway())
    workspace = harness.init_workspace("demo")
    (workspace / "sources/requirement.md").write_text("requirement", encoding="utf-8")
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test"))
    budget = Budget()
    events: list[dict[str, object]] = []
    runtime = ToolRuntime(
        store=harness.store,
        agents=harness.agents,
        tools=harness.tools,
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
    harness.init_workspace("demo")
    runtime_without_mcp = ToolRuntime(
        store=harness.store,
        agents=harness.agents,
        tools=harness.tools,
        budget=Budget(),
    )

    assert [
        item["name"]
        for item in runtime_without_mcp.model_tools(
            harness.agents.get("ui_test_engineer").tool_allowlist
        )
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
        store=harness.store,
        agents=harness.agents,
        tools=harness.tools,
        budget=Budget(),
        handlers={"mcp.playwright": bridge.tool_handler},
    )

    visible = runtime.model_tools(harness.agents.get("ui_test_engineer").tool_allowlist)
    mcp = next(item for item in visible if item["name"] == "mcp.playwright")
    variants = mcp["input_schema"]["oneOf"]
    assert [item["properties"]["tool"]["const"] for item in variants] == ["browser_snapshot"]
    assert variants[0]["properties"]["arguments"]["additionalProperties"] is False
