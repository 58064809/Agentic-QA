from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.cli import build_parser  # noqa: E402
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
        "skills/test-design-skill.md",
        "knowledge/templates/testcase-template.md",
        "prd/demo-requirement/metadata.yml",
        "prd/demo-requirement/requirement.md",
    ]
    for relative_path in required_files:
        write_file(root / relative_path)
    (root / "prd/demo-requirement/20-testcases").mkdir(parents=True, exist_ok=True)
    return root


def test_intent_router_recognizes_testcase_generation():
    state = QAWorkflowState(user_input="请生成测试用例", prd_path="prd/demo-requirement")

    intent_router_node(state)

    assert state.intent == "testcase_generation"
    assert not state.errors


def test_intent_router_rejects_unsupported_intent():
    state = QAWorkflowState(user_input="请归档这个需求", prd_path="prd/demo-requirement")

    intent_router_node(state)

    assert state.intent is None
    assert state.errors == ["当前 Runtime Skeleton 仅支持测试用例生成 dry-run。"]


def test_context_loader_loads_sample_prd_required_files():
    state = QAWorkflowState(
        user_input="请生成测试用例",
        prd_path="prd/sample-login-requirement",
    )

    context_loader_node(state, REPO_ROOT)

    assert "prd/sample-login-requirement/metadata.yml" in state.loaded_files
    assert "prd/sample-login-requirement/requirement.md" in state.loaded_files
    assert state.output_path == "prd/sample-login-requirement/20-testcases/testcases.md"


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
    assert not (repo_root / "prd/demo-requirement/20-testcases/testcases.md").exists()


def test_approve_write_creates_testcase_draft_when_missing(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    output_path = repo_root / "prd/demo-requirement/20-testcases/testcases.md"
    content = output_path.read_text(encoding="utf-8")
    assert result.success
    assert result.wrote_file
    assert "Runtime Skeleton" in content
    assert "needs_human_review" in content


def test_approve_write_does_not_overwrite_existing_testcases(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    output_path = repo_root / "prd/demo-requirement/20-testcases/testcases.md"
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
        output_path="prd/demo-requirement/20-testcases/testcases.md",
    )

    quality_check_node(state, repo_root)

    assert "测试用例草稿缺少 needs_human_review 状态。" in state.quality_errors
    assert any("测试用例草稿缺少表头" in error for error in state.quality_errors)


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "runtime.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0
    assert "Agentic-QA Runtime" in result.stdout
    assert "confirm" in result.stdout


def test_confirm_command_parses_one_click_write():
    args = build_parser().parse_args(
        ["confirm", "帮我分析需求并生成测试用例", "--prd", "prd/demo-requirement"]
    )

    assert args.command == "confirm"
    assert args.prd == "prd/demo-requirement"


def test_confirm_alias_parses_for_mvp():
    args = build_parser().parse_args(
        ["mvp", "帮我分析需求并生成测试用例", "--prd", "prd/demo-requirement", "--confirm"]
    )

    assert args.command == "mvp"
    assert args.confirm is True
