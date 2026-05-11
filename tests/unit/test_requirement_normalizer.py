from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.graph.mvp_graph import run_requirement_analysis_workflow  # noqa: E402
from runtime.graph.nodes import requirement_normalizer  # noqa: E402
from runtime.graph.nodes.requirement_normalizer import (  # noqa: E402
    normalize_requirement_document,
)
from runtime.graph.state import QAWorkflowState  # noqa: E402


def write_file(path: Path, content: str = "placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_repo(root: Path, *, with_requirement_md: bool = False) -> Path:
    for relative_path, content in {
        "AGENTS.md": "Agent 协作规范",
        "COMMANDS.md": "命令路由",
        "docs/architecture/production-agent-runtime-roadmap.md": "Runtime 路线图",
        "workflows/01-requirement-analysis-workflow.md": "需求分析工作流",
        "workflows/10-runtime-testcase-generation-workflow.md": "Runtime 测试用例工作流",
        "workflows/02-testcase-generation-workflow.md": "测试用例工作流",
        "prompts/requirement-analysis-prompt.md": "需求分析 Prompt",
        "prompts/testcase-design-prompt.md": "测试用例 Prompt",
        "rules/requirement-analysis-rules.md": "需求分析规则",
        "rules/testcase-rules.md": "测试用例规则",
        "rules/review-gate-rules.md": "审核门规则",
        "rules/artifact-path-rules.md": "产物路径规则",
        "skills/requirement-decomposition-skill.md": "需求拆解技能",
        "skills/business-rule-extraction-skill.md": "业务规则提取技能",
        "knowledge/templates/requirement-analysis-template.md": "需求分析模板",
        "knowledge/templates/prototype-notes-template.md": "原型说明模板",
        "skills/test-design-skill.md": "测试设计技能",
        "skills/equivalence-partitioning-skill.md": "等价类技能",
        "skills/boundary-value-analysis-skill.md": "边界值技能",
        "skills/scenario-modeling-skill.md": "场景建模技能",
        "skills/state-transition-modeling-skill.md": "状态迁移技能",
        "skills/risk-based-testing-skill.md": "风险测试技能",
        "knowledge/templates/testcase-template.md": "测试用例模板",
        "prd/demo-requirement/metadata.yml": "id: demo-requirement\n",
    }.items():
        write_file(root / relative_path, content)
    if with_requirement_md:
        write_file(root / "prd/demo-requirement/requirement.md", "# Requirement\n")
    return root


def normalize(repo_root: Path) -> QAWorkflowState:
    state = QAWorkflowState(user_input="请分析", prd_path="prd/demo-requirement")
    return normalize_requirement_document(state, repo_root)


def test_existing_requirement_markdown_skips_conversion(tmp_path):
    repo_root = create_repo(tmp_path, with_requirement_md=True)
    write_file(repo_root / "prd/demo-requirement/requirement.txt", "# Source\n")

    state = normalize(repo_root)

    assert not state.errors
    assert state.requirement_normalization == {
        "performed": False,
        "source_path": "prd/demo-requirement/requirement.md",
        "output_path": "prd/demo-requirement/requirement.md",
        "source_type": "markdown",
        "skipped_reason": "requirement.md already exists",
    }
    assert (repo_root / "prd/demo-requirement/requirement.md").read_text(
        encoding="utf-8"
    ) == "# Requirement\n"


def test_requirement_txt_converts_to_markdown(tmp_path):
    repo_root = create_repo(tmp_path)
    write_file(
        repo_root / "prd/demo-requirement/requirement.txt",
        "# Login Requirement\n\nUser can login.",
    )

    state = normalize(repo_root)

    assert not state.errors
    assert state.requirement_normalization["performed"] is True
    assert state.requirement_normalization["source_type"] == "txt"
    assert (repo_root / "prd/demo-requirement/requirement.md").is_file()


def test_missing_requirement_source_returns_clear_error(tmp_path):
    repo_root = create_repo(tmp_path)

    state = normalize(repo_root)

    assert state.errors
    assert "未找到需求源文件" in state.errors[0]
    assert (
        state.requirement_normalization["skipped_reason"]
        == "no supported requirement source found"
    )


def test_multiple_requirement_sources_use_priority_with_warning(tmp_path):
    repo_root = create_repo(tmp_path)
    write_file(repo_root / "prd/demo-requirement/requirement.pdf", "fake pdf")
    write_file(repo_root / "prd/demo-requirement/requirement.txt", "# Text Requirement\n")

    state = normalize(repo_root)

    assert state.requirement_normalization["source_path"] == "prd/demo-requirement/requirement.pdf"
    assert (repo_root / "prd/demo-requirement/requirement.md").is_file()
    assert any("发现多个需求源文件" in warning for warning in state.warnings)


def test_normalize_then_analyze_flow_reads_generated_markdown(tmp_path):
    repo_root = create_repo(tmp_path)
    write_file(
        repo_root / "prd/demo-requirement/requirement.txt",
        "# 登录需求\n\n"
        "## 背景\n\n用户通过手机号密码登录，成功后返回 token。\n\n"
        "## 功能范围\n\n"
        "- 用户输入手机号和密码后发起登录。\n"
        "- 登录成功后返回 token。\n\n"
        "## 验收标准\n\n"
        "- 正确手机号和密码可以登录成功。\n"
        "- token 过期后必须重新登录。\n",
    )

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    assert result.requirement_normalization["performed"] is True
    assert "prd/demo-requirement/requirement.md" in result.loaded_files


def test_conversion_failure_is_reported(tmp_path, monkeypatch):
    repo_root = create_repo(tmp_path)
    write_file(repo_root / "prd/demo-requirement/requirement.txt", "source")

    def fail_conversion(*args, **kwargs):
        raise RuntimeError("MarkItDown 转换失败: boom")

    monkeypatch.setattr(requirement_normalizer, "convert_requirement_to_markdown", fail_conversion)

    state = normalize(repo_root)

    assert state.errors == ["MarkItDown 转换失败: boom"]
    assert state.requirement_normalization["skipped_reason"] == "conversion failed"
