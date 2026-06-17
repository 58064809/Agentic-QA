from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_runtime_mvp_generation import create_mvp_repo  # noqa: E402

from runtime.graph.app import resume_recorded_workflow  # noqa: E402
from runtime.workflow import load_workflow_spec, run_workflow_by_id  # noqa: E402
from runtime.workflow.builder import build_graph_from_spec  # noqa: E402
from runtime.workflow.loader import load_workflow_spec_by_id  # noqa: E402
from runtime.workflow.runner import resume_workflow_for_run  # noqa: E402


def test_load_runtime_workflow_spec_from_yaml():
    spec = load_workflow_spec(REPO_ROOT / "workflows/runtime/analysis-and-testcases.workflow.yml")

    assert spec.id == "analysis_and_testcases"
    assert spec.state["task_type"] == "mvp_analysis_testcases"
    assert {node.id for node in spec.nodes} >= {
        "command_router",
        "context_loader",
        "testcase_generator",
        "metadata_update",
    }
    assert any(edge.condition == "task_is_mvp" for edge in spec.edges)


def test_build_graph_from_workflow_spec_validates_handlers():
    specs = [
        load_workflow_spec_by_id(REPO_ROOT, "requirement_analysis"),
        load_workflow_spec_by_id(REPO_ROOT, "testcase_generation"),
        load_workflow_spec_by_id(REPO_ROOT, "analysis_and_testcases"),
    ]

    for spec in specs:
        graph = build_graph_from_spec(spec, REPO_ROOT)

        assert hasattr(graph, "invoke")


def test_run_workflow_by_id_returns_runtime_result(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_workflow_by_id(
        "testcase_generation",
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
        use_llm=False,
    )

    assert result.success
    assert result.orchestration == "YAML WorkflowSpec: testcase_generation"
    assert result.task_type == "testcase_generation"
    assert result.review_status == "needs_human_review"
    assert "testcase_generation_node" in result.executed_nodes
    assert "testcases" in result.draft_artifacts


def test_run_requirement_analysis_workflow_by_id_returns_runtime_result(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_workflow_by_id(
        "requirement_analysis",
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
        use_llm=False,
    )

    assert result.success
    assert result.orchestration == "YAML WorkflowSpec: requirement_analysis"
    assert result.task_type == "analysis"
    assert result.review_status == "needs_human_review"
    assert "requirement_analysis_generation_node" in result.executed_nodes
    assert "requirement_analysis" in result.draft_artifacts
    assert "testcases" not in result.draft_artifacts


def test_resume_workflow_for_run_uses_recorded_task_type(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_workflow_by_id(
        "requirement_analysis",
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
        use_llm=False,
    )

    resumed = resume_workflow_for_run(
        result.run_id or "",
        repo_root=repo_root,
    )

    assert resumed.success
    assert resumed.run_id == result.run_id
    assert resumed.task_type == "analysis"
    assert resumed.orchestration == "YAML WorkflowSpec: requirement_analysis"
    assert "requirement_analysis_generation_node" in resumed.executed_nodes


def test_resume_recorded_workflow_routes_mvp_task_type_to_runtime_dsl(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_workflow_by_id(
        "testcase_generation",
        "generate testcases",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
        use_llm=False,
    )

    resumed = resume_recorded_workflow(
        result.run_id or "",
        repo_root=repo_root,
    )

    assert resumed.success
    assert resumed.run_id == result.run_id
    assert resumed.task_type == "testcase_generation"
    assert resumed.orchestration == "YAML WorkflowSpec: testcase_generation"
    assert "testcase_generation_node" in resumed.executed_nodes
