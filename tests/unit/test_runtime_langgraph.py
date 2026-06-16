from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import runtime.graph.langgraph_app as langgraph_app  # noqa: E402
from runtime.graph.langgraph_app import (  # noqa: E402
    build_testcase_generation_graph,
    run_langgraph_testcase_generation_workflow,
)


def write_file(path: Path, content: str = "placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_runtime_repo(root: Path) -> Path:
    required_files = [
        "AGENTS.md",
        "COMMANDS.md",
        "docs/roadmap.md",
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/02-testcase-generation-workflow.md",
        "prompts/testcase-design-prompt.md",
        "rules/testcase-rules.md",
        "rules/review-gate-rules.md",
        "rules/artifact-path-rules.md",
        "skills/test-design/test-design-skill.md",
        "knowledge/templates/testcase-template.md",
        "prd/demo-requirement/metadata.yml",
        "prd/demo-requirement/input/requirement.md",
    ]
    for relative_path in required_files:
        write_file(root / relative_path)
    (root / "prd/demo-requirement/runs").mkdir(parents=True, exist_ok=True)
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
    assert result.run_status == "waiting_review"
    assert result.review_status == "needs_human_review"
    assert not result.wrote_file
    assert "artifact_writer_node" not in result.executed_nodes
    preview_path = repo_root / f"prd/demo-requirement/runs/{result.run_id}/artifact-preview.md"
    assert not preview_path.exists()


def test_langgraph_approve_write_creates_testcase_draft(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_langgraph_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    output_path = repo_root / f"prd/demo-requirement/runs/{result.run_id}/artifact-preview.md"
    assert result.success
    assert result.wrote_file
    assert result.run_status == "completed"
    assert result.review_status == "write_approved"
    assert "Runtime Skeleton" in output_path.read_text(encoding="utf-8")

    assert result.run_record_dir is not None
    metadata = yaml.safe_load(
        (repo_root / "prd/demo-requirement/metadata.yml").read_text(encoding="utf-8")
    )
    assert metadata["status"] == "needs_human_review"
    assert metadata["last_runtime_run"]["run_id"] == result.run_id
    assert metadata["runtime_runs"][-1]["wrote_file"] is True
    assert metadata["runtime_runs"][-1]["review_status"] == "write_approved"


def test_langgraph_approve_write_does_not_overwrite_existing_testcases(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    formal_path = repo_root / "prd/demo-requirement/artifacts/testcases.md"
    write_file(formal_path, "人工已有内容")

    result = run_langgraph_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    assert result.success
    assert result.wrote_file
    assert formal_path.read_text(encoding="utf-8") == "人工已有内容"


def test_langgraph_known_intent_proceeds_to_workflow_selector(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_langgraph_testcase_generation_workflow(
        "请归档这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    # "归档" 是已识别的意图，所以会继续到 workflow_selector_node
    assert result.intent == "archive"
    assert "intent_router_node" in result.executed_nodes
    # workflow_selector 只检查文件是否存在，不检查意图匹配—所以继续执行
    assert "workflow_selector_node" in result.executed_nodes


def test_langgraph_unknown_intent_stops_before_workflow_selector(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_langgraph_testcase_generation_workflow(
        "帮我浇花",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    assert not result.success
    assert result.intent is None
    assert "intent_router_node" in result.executed_nodes
    assert "workflow_selector_node" not in result.executed_nodes
    assert "context_loader_node" not in result.executed_nodes
    assert "artifact_generation_node" not in result.executed_nodes


def test_langgraph_missing_prd_required_file_stops_before_generation(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    (repo_root / "prd/demo-requirement/input/requirement.md").unlink()

    result = run_langgraph_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )

    assert not result.success
    assert "context_loader_node" in result.executed_nodes
    assert "artifact_generation_node" not in result.executed_nodes
    assert "artifact_writer_node" not in result.executed_nodes
    preview_path = repo_root / f"prd/demo-requirement/runs/{result.run_id}/artifact-preview.md"
    assert not preview_path.exists()


def test_langgraph_quality_failure_stops_before_writer(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)

    def fake_artifact_generation_node(state):
        state.record_node("artifact_generation_node")
        state.draft_artifact = "缺少审核状态和表头"
        return state

    monkeypatch.setattr(
        langgraph_app,
        "artifact_generation_node",
        fake_artifact_generation_node,
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
