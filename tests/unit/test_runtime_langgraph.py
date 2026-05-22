from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import runtime.graph.langgraph_app as langgraph_app  # noqa: E402
from runtime.graph.langgraph_app import (  # noqa: E402
    build_testcase_generation_graph,
    resume_langgraph_testcase_generation_workflow,
    run_langgraph_testcase_generation_workflow,
)


def write_file(path: Path, content: str = "placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_runtime_repo(root: Path) -> Path:
    required_files = [
        "AGENTS.md",
        "COMMANDS.md",
        "docs/architecture/production-agent-runtime-roadmap.md",
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/02-testcase-generation-workflow.md",
        "prompts/testcase-design-prompt.md",
        "rules/testcase-rules.md",
        "rules/review-gate-rules.md",
        "rules/artifact-path-rules.md",
        "skills/test-design-skill.md",
        "knowledge/templates/testcase-template.md",
        "prd/demo-requirement/metadata.yml",
        "prd/demo-requirement/requirement.md",
    ]
    for relative_path in required_files:
        write_file(root / relative_path)
    (root / "prd/demo-requirement/20-testcases").mkdir(parents=True, exist_ok=True)
    return root


def test_build_testcase_generation_graph_succeeds(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    graph = build_testcase_generation_graph(repo_root)

    assert hasattr(graph, "invoke")


def test_langgraph_dry_run_does_not_write_testcases(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_langgraph_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    assert result.success
    assert result.orchestration == "LangGraph StateGraph"
    assert result.run_status == "interrupted"
    assert result.review_status == "needs_human_review"
    assert not result.wrote_file
    assert "artifact_writer_node" not in result.executed_nodes
    assert not (repo_root / "prd/demo-requirement/20-testcases/testcases.md").exists()


def test_langgraph_approve_write_creates_testcase_draft(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_langgraph_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    assert result.run_id is not None
    result = resume_langgraph_testcase_generation_workflow(
        result.run_id,
        repo_root=repo_root,
        action="approve",
    )

    output_path = repo_root / "prd/demo-requirement/20-testcases/testcases.md"
    assert result.success
    assert result.wrote_file
    assert "Runtime Skeleton" in output_path.read_text(encoding="utf-8")


def test_langgraph_approve_write_does_not_overwrite_existing_testcases(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    output_path = repo_root / "prd/demo-requirement/20-testcases/testcases.md"
    write_file(output_path, "人工已有内容")

    result = run_langgraph_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    assert result.run_id is not None
    result = resume_langgraph_testcase_generation_workflow(
        result.run_id,
        repo_root=repo_root,
        action="approve",
    )

    assert not result.success
    assert not result.wrote_file
    assert output_path.read_text(encoding="utf-8") == "人工已有内容"
    assert any("默认不覆盖" in error for error in result.errors)


def test_langgraph_reject_does_not_write_testcase_draft(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_langgraph_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    assert result.run_id is not None
    result = resume_langgraph_testcase_generation_workflow(
        result.run_id,
        repo_root=repo_root,
        action="reject",
    )

    assert result.success
    assert result.run_status == "rejected"
    assert result.review_status == "rejected"
    assert not result.wrote_file
    assert not (repo_root / "prd/demo-requirement/20-testcases/testcases.md").exists()


def test_langgraph_unsupported_intent_stops_before_context_loader(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_langgraph_testcase_generation_workflow(
        "请归档这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    assert not result.success
    assert "intent_router_node" in result.executed_nodes
    assert "context_loader_node" not in result.executed_nodes
    assert "testcase_generation_node" not in result.executed_nodes
    assert "artifact_writer_node" not in result.executed_nodes


def test_langgraph_missing_prd_required_file_stops_before_generation(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    (repo_root / "prd/demo-requirement/requirement.md").unlink()

    result = run_langgraph_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )

    assert not result.success
    assert "context_loader_node" in result.executed_nodes
    assert "testcase_generation_node" not in result.executed_nodes
    assert "artifact_writer_node" not in result.executed_nodes
    assert not (repo_root / "prd/demo-requirement/20-testcases/testcases.md").exists()


def test_langgraph_quality_failure_stops_before_writer(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)

    def fake_testcase_generation_node(state):
        state.record_node("testcase_generation_node")
        state.draft_artifact = "缺少审核状态和表头"
        return state

    monkeypatch.setattr(
        langgraph_app,
        "testcase_generation_node",
        fake_testcase_generation_node,
    )

    result = run_langgraph_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )

    assert not result.success
    assert result.quality_errors
    assert "testcase_quality_check_node" in result.executed_nodes
    assert "artifact_writer_node" not in result.executed_nodes
