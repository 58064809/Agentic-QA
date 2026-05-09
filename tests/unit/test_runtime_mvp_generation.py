from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.graph.mvp_graph import (  # noqa: E402
    run_mvp_analysis_and_testcases_workflow,
    run_mvp_testcase_generation_workflow,
    run_requirement_analysis_workflow,
)
from runtime.llm.openai_compatible import OpenAICompatibleAdapter  # noqa: E402


def write_file(path: Path, content: str = "placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_mvp_repo(root: Path) -> Path:
    required_files = {
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
        "skills/test-design-skill.md": "测试设计技能",
        "knowledge/templates/testcase-template.md": "测试用例模板",
        "prd/demo-requirement/metadata.yml": "id: demo-requirement\n",
        "prd/demo-requirement/requirement.md": "# 登录需求\n\n用户使用手机号密码登录。\n",
    }
    for relative_path, content in required_files.items():
        write_file(root / relative_path, content)
    return root


def test_analyze_dry_run_generates_analysis_without_writing(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    assert result.task_type == "analysis"
    assert "requirement_analysis" in result.draft_artifacts
    assert "needs_human_review" in result.draft_artifacts["requirement_analysis"]
    assert not (repo_root / "prd/demo-requirement/10-analysis/requirement-analysis.md").exists()


def test_analyze_approve_write_creates_analysis_draft(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
        record_run=False,
    )

    output_path = repo_root / "prd/demo-requirement/10-analysis/requirement-analysis.md"
    assert result.success
    assert result.wrote_file
    assert "artifact_type: requirement_analysis" in output_path.read_text(encoding="utf-8")


def test_generate_testcases_dry_run_generates_testcases_without_writing(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    assert result.task_type == "testcase_generation"
    assert "testcases" in result.draft_artifacts
    assert "| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |" in result.draft_artifacts[
        "testcases"
    ]
    assert not (repo_root / "prd/demo-requirement/20-testcases/testcases.md").exists()


def test_generate_testcases_approve_write_creates_testcase_draft(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
        record_run=False,
    )

    output_path = repo_root / "prd/demo-requirement/20-testcases/testcases.md"
    assert result.success
    assert result.wrote_file
    assert "artifact_type: testcase_draft" in output_path.read_text(encoding="utf-8")


def test_mvp_dry_run_generates_two_drafts_without_writing(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    assert result.task_type == "mvp_analysis_testcases"
    assert set(result.draft_artifacts) == {"requirement_analysis", "testcases"}
    assert not (repo_root / "prd/demo-requirement/10-analysis/requirement-analysis.md").exists()
    assert not (repo_root / "prd/demo-requirement/20-testcases/testcases.md").exists()


def test_mvp_approve_write_creates_analysis_and_testcases(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
        record_run=False,
    )

    assert result.success
    assert result.wrote_file
    assert (repo_root / "prd/demo-requirement/10-analysis/requirement-analysis.md").is_file()
    assert (repo_root / "prd/demo-requirement/20-testcases/testcases.md").is_file()


def test_mvp_approve_write_refuses_partial_overwrite(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    existing_analysis = repo_root / "prd/demo-requirement/10-analysis/requirement-analysis.md"
    write_file(existing_analysis, "人工已有分析")

    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
        record_run=False,
    )

    assert not result.success
    assert not result.wrote_file
    assert existing_analysis.read_text(encoding="utf-8") == "人工已有分析"
    assert not (repo_root / "prd/demo-requirement/20-testcases/testcases.md").exists()
    assert any("本次未写入任何产物" in error for error in result.errors)


def test_use_llm_without_api_key_degrades_to_skeleton(tmp_path, monkeypatch):
    repo_root = create_mvp_repo(tmp_path)
    monkeypatch.delenv("FREEMODEL_API_KEY", raising=False)

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        use_llm=True,
        record_run=False,
    )

    assert result.success
    assert result.llm["enabled"] is True
    assert result.llm["used"] is False
    assert result.llm["calls"] == 0
    assert any("已降级为 Skeleton 生成" in warning for warning in result.warnings)


def test_run_record_does_not_store_llm_secret(tmp_path, monkeypatch):
    repo_root = create_mvp_repo(tmp_path)
    monkeypatch.setenv("FREEMODEL_API_KEY", "secret-token-should-not-be-stored")
    monkeypatch.setenv("FREEMODEL_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("FREEMODEL_MODEL", "demo-model")
    monkeypatch.setattr(
        OpenAICompatibleAdapter,
        "generate_text",
        lambda self, prompt: """---
status: needs_human_review
artifact_type: requirement_analysis
human_review_required: true
---

# 需求分析草稿

## 需求概述
## 业务规则
## 流程拆解
## 角色与权限
## 数据与状态
## 异常与边界
## 风险点
## 待确认问题
""",
    )

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        use_llm=True,
    )

    assert result.run_summary_json is not None
    summary_text = (repo_root / result.run_summary_json).read_text(encoding="utf-8")
    summary = json.loads(summary_text)
    assert "secret-token-should-not-be-stored" not in summary_text
    assert "api_key" not in summary_text
    assert summary["llm"]["base_url"] == "https://example.test/v1"
    assert summary["llm"]["model"] == "demo-model"
    assert summary["llm"]["calls"] == 1
