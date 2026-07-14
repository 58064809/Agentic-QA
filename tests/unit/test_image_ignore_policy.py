from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.graph.app import (  # noqa: E402
    run_requirement_analysis_workflow,
    run_testcase_generation_workflow,
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
        "docs/roadmap.md": "Runtime 路线图",
        "workflows/runtime/analysis-and-testcases.workflow.yml": (
            REPO_ROOT / "workflows/runtime/analysis-and-testcases.workflow.yml"
        ).read_text(encoding="utf-8"),
        "workflows/runtime/requirement-analysis.workflow.yml": (
            REPO_ROOT / "workflows/runtime/requirement-analysis.workflow.yml"
        ).read_text(encoding="utf-8"),
        "workflows/runtime/testcase-generation.workflow.yml": (
            REPO_ROOT / "workflows/runtime/testcase-generation.workflow.yml"
        ).read_text(encoding="utf-8"),
        "prompts/requirement-analysis-prompt.md": "需求分析 Prompt",
        "prompts/testcase-design-prompt.md": "测试用例 Prompt",
        "rules/requirement-analysis-rules.md": "需求分析规则",
        "rules/testcase-rules.md": "测试用例规则",
        "rules/review-gate-rules.md": "审核门规则",
        "rules/artifact-path-rules.md": "产物路径规则",
        "skills/registry/skills.yaml": """version: 1
required_first_version: true
skills:
  - id: S1
    file: skills/core/requirement-understanding-skill.md
  - id: S2
    file: skills/core/context-building-skill.md
  - id: S3
    file: skills/core/rag-retrieval-skill.md
  - id: S4
    file: skills/analysis/test-scope-decomposition-skill.md
  - id: S5
    file: skills/analysis/risk-identification-skill.md
  - id: S6
    file: skills/test-design/test-method-selection-skill.md
  - id: S7
    file: skills/test-design/testcase-generation-skill.md
  - id: S8
    file: skills/test-design/testcase-review-skill.md
  - id: S9
    file: skills/core/output-formatting-skill.md
  - id: S10
    file: skills/knowledge/knowledge-capture-skill.md
""",
        "skills/core/requirement-understanding-skill.md": "需求理解 Skill",
        "skills/core/context-building-skill.md": "上下文构建 Skill",
        "skills/core/rag-retrieval-skill.md": "RAG 检索 Skill",
        "skills/analysis/test-scope-decomposition-skill.md": "测试范围拆解 Skill",
        "skills/analysis/risk-identification-skill.md": "风险识别 Skill",
        "skills/test-design/test-method-selection-skill.md": "测试方法选择 Skill",
        "skills/test-design/testcase-generation-skill.md": "测试用例生成 Skill",
        "skills/test-design/testcase-review-skill.md": "用例评审 Skill",
        "skills/core/output-formatting-skill.md": "输出格式化 Skill",
        "skills/knowledge/knowledge-capture-skill.md": "知识沉淀 Skill",
        "skills/analysis/requirement-decomposition-skill.md": "需求拆解技能",
        "skills/analysis/business-rule-extraction-skill.md": "业务规则提取技能",
        "knowledge/templates/requirement-analysis-template.md": "需求分析模板",
        "skills/test-design/test-design-skill.md": "测试设计技能",
        "skills/test-design/equivalence-partitioning-skill.md": "等价类技能",
        "skills/test-design/boundary-value-analysis-skill.md": "边界值技能",
        "skills/test-design/scenario-modeling-skill.md": "场景建模技能",
        "skills/test-design/state-transition-modeling-skill.md": "状态迁移技能",
        "skills/test-design/risk-based-testing-skill.md": "风险测试技能",
        "knowledge/templates/testcase-template.md": "测试用例模板",
        "prd/demo-requirement/metadata.yml": "requirement_id: demo-requirement\n",
        "prd/demo-requirement/input/requirement.md": requirement
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
        use_llm=False,
    )
    testcase_result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
        use_llm=False,
    )

    assert analysis_result.success
    assert analysis_result.prototype_notes["requirement_has_images"] is False
    assert analysis_result.prototype_notes["warning"] is None
    assert not any("prototype-notes" in warning for warning in analysis_result.warnings)
    assert testcase_result.success
    assert testcase_result.prototype_notes["warning"] is None
    assert not any("prototype-notes" in warning for warning in testcase_result.warnings)


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
        use_llm=False,
    )

    assert result.prototype_notes["requirement_has_images"] is True
    assert result.prototype_notes["loaded"] is False
    assert any("当前 Runtime 不分析图片内容" in warning for warning in result.warnings)
    assert (
        "请人工确认图片中是否存在未写入正文的字段、按钮、状态、弹窗、权限差异或交互规则"
        in result.prototype_notes["warning"]
    )
    assert result.prototype_notes["warning"]
    assert result.prototype_notes["requirement_has_images"] is True


def test_existing_prototype_notes_are_ignored(tmp_path):
    repo_root = create_repo(tmp_path)
    write_file(repo_root / "prd/demo-requirement/prototype-notes.md", prototype_notes_content())

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
        use_llm=False,
    )

    assert result.success
    assert result.prototype_notes["loaded"] is False
    assert result.prototype_notes["path"] is None
    assert "prd/demo-requirement/prototype-notes.md" not in result.loaded_files
    assert "会员等级徽章" not in result.draft_artifacts["requirement_analysis"]


def test_llm_prompts_do_not_include_prototype_notes_content():
    loaded_files = {
        "prd/demo-requirement/input/requirement.md": "# 登录需求\n\n![原型](login.jpg)",
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
        use_llm=False,
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

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
        use_llm=False,
    )

    assert result.success
    testcases = result.draft_artifacts["testcases"]
    assert result.prototype_notes["requirement_has_images"] is True
    assert "会员等级徽章" not in testcases
    assert "批量确认按钮" not in testcases
    assert "登录按钮置灰后弹窗确认" not in testcases
