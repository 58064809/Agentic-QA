from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.graph.mvp_graph import (  # noqa: E402
    run_mvp_testcase_generation_workflow,
    run_requirement_analysis_workflow,
)
from runtime.llm.prompt_builder import (  # noqa: E402
    build_requirement_analysis_prompt,
    build_testcase_prompt,
)


def write_file(path: Path, content: str = "placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_repo(root: Path, *, requirement: str | None = None) -> Path:
    files = {
        "AGENTS.md": "Agent 协作规范",
        "COMMANDS.md": "命令路由",
        "docs/production-agent-runtime-roadmap.md": "Runtime 路线图",
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
        "skills/test-design-skill.md": "测试设计技能",
        "skills/equivalence-partitioning-skill.md": "等价类技能",
        "skills/boundary-value-analysis-skill.md": "边界值技能",
        "skills/scenario-modeling-skill.md": "场景建模技能",
        "skills/state-transition-modeling-skill.md": "状态迁移技能",
        "skills/risk-based-testing-skill.md": "风险测试技能",
        "knowledge/templates/testcase-template.md": "测试用例模板",
        "prd/demo-requirement/metadata.yml": "id: demo-requirement\n",
        "prd/demo-requirement/requirement.md": requirement
        or (
            "# 登录需求\n\n"
            "## 背景\n\n用户使用手机号密码登录。\n\n"
            "## 功能范围\n\n"
            "- 用户输入手机号和密码后发起登录。\n"
            "- 登录成功后返回访问 token。\n\n"
            "## 验收标准\n\n"
            "- 正确手机号和密码可以登录成功。\n"
            "- token 过期后必须重新登录。\n"
        ),
    }
    for relative_path, content in files.items():
        write_file(root / relative_path, content)
    return root


def prototype_notes_content() -> str:
    return """# 原型图说明

- 原型专属字段：会员等级徽章
- 原型专属按钮：批量确认按钮
- 原型专属交互：登录按钮置灰后弹窗确认
"""


def test_no_image_does_not_warn_about_prototype_notes(tmp_path):
    repo_root = create_repo(tmp_path)

    analysis_result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )
    mvp_result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert analysis_result.success
    assert analysis_result.prototype_notes["requirement_has_images"] is False
    assert analysis_result.prototype_notes["warning"] is None
    assert not any("prototype-notes" in warning for warning in analysis_result.warnings)
    assert mvp_result.success
    assert mvp_result.prototype_notes["warning"] is None
    assert not any("prototype-notes" in warning for warning in mvp_result.warnings)


def test_requirement_image_reference_produces_strong_warning(tmp_path):
    repo_root = create_repo(
        tmp_path,
        requirement="# 登录需求\n\n![登录原型](images/login.png)\n\n用户通过手机号密码登录。",
    )

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.prototype_notes["requirement_has_images"] is True
    assert result.prototype_notes["loaded"] is False
    assert any("当前 Runtime 不分析图片内容" in warning for warning in result.warnings)
    assert (
        "请人工确认图片中是否存在未写入正文的字段、按钮、状态、弹窗、权限差异或交互规则"
        in result.prototype_notes["warning"]
    )
    assert (
        "需求文档包含图片/原型图引用，但当前 Runtime 未分析图片内容"
        in result.draft_artifacts["requirement_analysis"]
    )


def test_existing_prototype_notes_are_ignored(tmp_path):
    repo_root = create_repo(tmp_path)
    write_file(repo_root / "prd/demo-requirement/prototype-notes.md", prototype_notes_content())

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    assert result.prototype_notes["loaded"] is False
    assert result.prototype_notes["path"] is None
    assert "prd/demo-requirement/prototype-notes.md" not in result.loaded_files
    assert "会员等级徽章" not in result.draft_artifacts["requirement_analysis"]


def test_llm_prompts_do_not_include_prototype_notes_content():
    loaded_files = {
        "prd/demo-requirement/requirement.md": "# 登录需求\n\n![原型](login.jpg)",
        "prd/demo-requirement/prototype-notes.md": "原型专属按钮：批量确认按钮",
        "knowledge/templates/prototype-notes-template.md": "# 原型图说明",
    }

    analysis_prompt = build_requirement_analysis_prompt(
        loaded_files,
        prd_prefix="prd/demo-requirement",
    )
    testcase_prompt = build_testcase_prompt(
        loaded_files,
        prd_prefix="prd/demo-requirement",
    )

    assert "原型专属按钮：批量确认按钮" not in analysis_prompt.prompt
    assert "原型专属按钮：批量确认按钮" not in testcase_prompt.prompt
    assert "knowledge/templates/prototype-notes-template.md" not in analysis_prompt.prompt
    assert "knowledge/templates/prototype-notes-template.md" not in testcase_prompt.prompt
    assert "禁止猜测图片中的字段、按钮、页面布局和交互" in analysis_prompt.prompt
    assert "禁止猜测图片中的字段、按钮、页面布局和交互" in testcase_prompt.prompt


def test_run_record_contains_image_detection_warning(tmp_path):
    repo_root = create_repo(
        tmp_path,
        requirement="# 登录需求\n\n原型资源：media/login.jpeg\n\n用户通过手机号密码登录。",
    )

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
    )
    summary_path = repo_root / result.run_summary_json
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert summary["image_detection"]["requirement_has_images"] is True
    assert "当前 Runtime 不分析图片内容" in summary["image_detection"]["warning"]
    assert summary["image_detection"]["loaded"] is False


def test_testcase_generation_does_not_invent_from_images_or_prototype_notes(tmp_path):
    repo_root = create_repo(
        tmp_path,
        requirement="# 登录需求\n\n![登录原型](login.png)\n\n用户通过手机号密码登录。",
    )
    write_file(repo_root / "prd/demo-requirement/prototype-notes.md", prototype_notes_content())

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    testcases = result.draft_artifacts["testcases"]
    assert "图片内容未分析的人工确认项已记录" in testcases
    assert "会员等级徽章" not in testcases
    assert "批量确认按钮" not in testcases
    assert "登录按钮置灰后弹窗确认" not in testcases
