from __future__ import annotations

from pathlib import Path

import pytest

from harness import Harness, TaskRequest
from harness.budget import Budget
from harness.contracts import ExecutionProfile
from harness.evals import recorded_model_gateway
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
