from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.graph.app import run_testcase_generation_workflow  # noqa: E402
from runtime.graph.nodes.context_loader import context_loader_node  # noqa: E402
from runtime.graph.nodes.intent_router import intent_router_node  # noqa: E402
from runtime.graph.nodes.quality_checker import (  # noqa: E402
    testcase_quality_check_node as quality_check_node,
)
from runtime.graph.state import QAWorkflowState  # noqa: E402


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
        "skills/test-design/test-design-skill.md",
        "knowledge/templates/testcase-template.md",
        "prd/demo-requirement/workspace.yml",
        "prd/demo-requirement/input/requirement.md",
    ]
    for relative_path in required_files:
        write_file(root / relative_path)
    (root / "prd/demo-requirement/cases").mkdir(parents=True, exist_ok=True)
    return root


def test_intent_router_recognizes_testcase_generation():
    state = QAWorkflowState(user_input="请生成测试用例", prd_path="prd/demo-requirement")

    intent_router_node(state)

    assert state.intent == "testcase_generation"
    assert not state.errors


def test_intent_router_recognizes_all_supported_intents():
    test_cases = [
        ("帮我分析登录需求", "requirement_analysis"),
        ("拆解需求并提取业务规则", "requirement_analysis"),
        ("生成测试用例覆盖边界场景", "testcase_generation"),
        ("设计用例补边界", "testcase_generation"),
        ("生成接口自动化", "api_test_generation"),
        ("根据接口文档出测试脚本", "api_test_generation"),
        ("生成 Playwright 脚本", "ui_test_generation"),
        ("做端到端测试", "ui_test_generation"),
        ("跑 pytest 收集结果", "test_execution"),
        ("执行测试并收集结果", "test_execution"),
        ("看失败日志判断原因", "failure_analysis"),
        ("分类这些失败", "failure_analysis"),
        ("生成 bug 草稿", "bug_draft"),
        ("提缺陷报告", "bug_draft"),
        ("生成 QA 报告草稿", "report_generation"),
        ("汇总测试结果", "report_generation"),
        ("归档这个需求", "archive"),
    ]
    for user_input, expected_intent in test_cases:
        state = QAWorkflowState(user_input=user_input, prd_path="prd/demo-requirement")
        intent_router_node(state)
        assert state.intent == expected_intent, (
            f"输入「{user_input}」应匹配意图 {expected_intent}，实际得到 {state.intent}"
        )
        assert not state.errors, (
            f"输入「{user_input}」不应报错，实际得到 {state.errors}"
        )


def test_intent_router_unknown_input_reports_supported_list():
    state = QAWorkflowState(user_input="帮我浇花", prd_path="prd/demo-requirement")

    intent_router_node(state)

    assert state.intent is None
    assert len(state.errors) == 1
    assert "未能识别意图" in state.errors[0]
    assert "需求分析" in state.errors[0]


def test_context_loader_loads_sample_prd_required_files():
    state = QAWorkflowState(
        user_input="请生成测试用例",
        prd_path="prd/sample-login-requirement",
    )

    context_loader_node(state, REPO_ROOT)

    assert "prd/sample-login-requirement/workspace.yml" in state.loaded_files
    assert "prd/sample-login-requirement/input/requirement.md" in state.loaded_files
    assert state.output_path == "prd/sample-login-requirement/cases/test-cases.md"


def test_dry_run_does_not_write_testcases(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    assert result.success
    assert result.dry_run
    assert not result.wrote_file
    assert not (repo_root / "prd/demo-requirement/cases/test-cases.md").exists()


def test_approve_write_creates_testcase_draft_when_missing(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    output_path = repo_root / "prd/demo-requirement/cases/test-cases.md"
    content = output_path.read_text(encoding="utf-8")
    assert result.success
    assert result.wrote_file
    assert "Runtime Skeleton" in content
    assert "needs_human_review" in content


def test_approve_write_does_not_overwrite_existing_testcases(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    output_path = repo_root / "prd/demo-requirement/cases/test-cases.md"
    write_file(output_path, "人工已有内容")

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    assert not result.success
    assert not result.wrote_file
    assert output_path.read_text(encoding="utf-8") == "人工已有内容"
    assert any("默认不覆盖" in error for error in result.errors)


def test_quality_check_reports_missing_review_status_and_headers(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    state = QAWorkflowState(
        user_input="请生成测试用例",
        prd_path="prd/demo-requirement",
        draft_artifact="缺少表格和审核状态",
        output_path="prd/demo-requirement/cases/test-cases.md",
    )

    quality_check_node(state, repo_root)

    assert "测试用例草稿缺少 needs_human_review 状态。" in state.quality_errors
    assert any("测试用例草稿缺少表头" in error for error in state.quality_errors)



