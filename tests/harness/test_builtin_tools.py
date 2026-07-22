from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import CreateWorkspaceCommand, Harness, StartRunCommand
from harness.budget import Budget
from harness.contracts import ExecutionProfile
from harness.infrastructure.manifests.registry import AgentRegistry, SkillRegistry, ToolRegistry
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.tools.runtime import ToolRuntime
from harness.testing.evals import recorded_model_gateway


def _runtime(tmp_path: Path):
    harness = Harness(tmp_path, model_gateway=recorded_model_gateway())
    workspace = harness.create_workspace(CreateWorkspaceCommand(workspace_id="demo"))
    (workspace / "sources/requirement.md").write_text(
        "登录连续失败五次后锁定账号。",
        encoding="utf-8",
    )
    snapshot = harness.start_run(
        StartRunCommand(
            workspace_id="demo",
            goal="analyze",
            expected_artifacts=["requirement_analysis"],
        )
    )
    store = FilesystemStore(tmp_path)
    tools = ToolRegistry.builtin()
    skills = SkillRegistry.builtin()
    agents = AgentRegistry.builtin(skills=skills, tools=tools)
    runtime = ToolRuntime(
        store=store,
        agents=agents,
        tools=tools,
        budget=Budget(),
    )
    return harness, workspace, snapshot, runtime


def test_rag_returns_traceable_chunks_and_workspace_read_is_isolated(tmp_path: Path) -> None:
    _, workspace, snapshot, runtime = _runtime(tmp_path)
    (workspace / "sources/requirement.md").write_text(
        "run 启动后被修改，不应进入已冻结的检索输入。", encoding="utf-8"
    )
    result = runtime.call(
        workspace="demo",
        run_id=snapshot.run_id,
        agent="requirement_analyst",
        tool="rag.retrieve",
        arguments={"query": "登录失败锁定"},
        profile=ExecutionProfile(),
    )
    assert result["chunks"][0]["source"] == "sources/requirement.md"
    assert result["chunks"][0]["chunk_id"].endswith("#chunk-0")
    assert result["chunks"][0]["selection_reason"].startswith("lexical_match:")

    with pytest.raises(ValueError, match="outside"):
        runtime.call(
            workspace="demo",
            run_id=snapshot.run_id,
            agent="requirement_analyst",
            tool="workspace.read",
            arguments={"path": "../outside.txt"},
            profile=ExecutionProfile(),
        )


def test_openapi_tool_only_confirms_complete_contract(tmp_path: Path) -> None:
    _, workspace, snapshot, runtime = _runtime(tmp_path)
    source = workspace / "sources/openapi.json"
    source.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "Demo", "version": "1"},
                "paths": {
                    "/health": {
                        "get": {
                            "operationId": "health",
                            "responses": {"200": {"description": "ok"}},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    result = runtime.call(
        workspace="demo",
        run_id=snapshot.run_id,
        agent="api_test_engineer",
        tool="openapi.inspect",
        arguments={"path": "sources/openapi.json"},
        profile=ExecutionProfile(),
    )
    assert result["contract_status"] == "confirmed"
    assert result["endpoints"] == [
        {
            "method": "GET",
            "path": "/health",
            "operation_id": "health",
            "summary": "",
        }
    ]

    source.write_text("# GET /health", encoding="utf-8")
    with pytest.raises(ValueError, match="complete OpenAPI"):
        runtime.call(
            workspace="demo",
            run_id=snapshot.run_id,
            agent="api_test_engineer",
            tool="openapi.inspect",
            arguments={"path": "sources/openapi.json"},
            profile=ExecutionProfile(),
        )
