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
    (workspace / "sources/openapi.json").write_text(
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
    (workspace / "sources/unavailable.bin").write_bytes(b"\xff\xfe")
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


def test_rag_uses_frozen_source_bundle(tmp_path: Path) -> None:
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


def test_workspace_read_rejects_source_added_after_run_start(tmp_path: Path) -> None:
    _, workspace, snapshot, runtime = _runtime(tmp_path)
    (workspace / "sources/new.md").write_text("new", encoding="utf-8")

    with pytest.raises(ValueError, match="不属于当前 Run"):
        runtime.call(
            workspace="demo",
            run_id=snapshot.run_id,
            agent="requirement_analyst",
            tool="workspace.read",
            arguments={"path": "sources/new.md"},
            profile=ExecutionProfile(),
        )


def test_workspace_read_uses_original_snapshot_after_workspace_source_changes(
    tmp_path: Path,
) -> None:
    _, workspace, snapshot, runtime = _runtime(tmp_path)
    (workspace / "sources/requirement.md").write_text("changed", encoding="utf-8")

    result = runtime.call(
        workspace="demo",
        run_id=snapshot.run_id,
        agent="requirement_analyst",
        tool="workspace.read",
        arguments={"path": "sources/requirement.md"},
        profile=ExecutionProfile(),
    )

    assert result["content"] == "登录连续失败五次后锁定账号。"


def test_workspace_read_rejects_unavailable_frozen_source(tmp_path: Path) -> None:
    _, _, snapshot, runtime = _runtime(tmp_path)

    with pytest.raises(ValueError, match="冻结 source 不可用"):
        runtime.call(
            workspace="demo",
            run_id=snapshot.run_id,
            agent="requirement_analyst",
            tool="workspace.read",
            arguments={"path": "sources/unavailable.bin"},
            profile=ExecutionProfile(),
        )


def test_openapi_inspect_uses_frozen_source_when_path_is_under_sources(tmp_path: Path) -> None:
    _, workspace, snapshot, runtime = _runtime(tmp_path)
    source = workspace / "sources/openapi.json"
    source.write_text("# changed after run start", encoding="utf-8")
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
