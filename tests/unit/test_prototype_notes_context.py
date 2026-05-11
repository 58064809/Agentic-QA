from __future__ import annotations

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

## 1. 原型图清单

| 编号 | 页面/弹窗 | 图片来源 | 说明状态 |
|---|---|---|---|
| P01 | 登录页 | login.png | needs_human_review |

## 2. 页面结构说明

### P01：登录页

- 页面入口：App 首页点击登录
- 页面目标：手机号密码登录
- 展示字段：手机号、密码
- 操作按钮：登录、忘记密码
- 默认状态：登录按钮置灰
- 空状态：无
- 异常状态：手机号格式错误、密码错误
- 权限差异：未登录用户可见
- 跳转逻辑：登录成功进入首页

## 3. 表单与字段规则

| 页面 | 字段 | 类型 | 必填 | 格式/范围 | 默认值 | 错误提示 | 备注 |
|---|---|---|---|---|---|---|---|
| 登录页 | 手机号 | 文本 | 是 | 大陆手机号 | 空 | 手机号格式不正确 | 无 |

## 4. 按钮与交互规则

| 页面 | 按钮/操作 | 可点击条件 | 点击后行为 | 成功反馈 | 失败反馈 | 防重复/幂等 |
|---|---|---|---|---|---|---|
| 登录页 | 登录 | 手机号和密码合法 | 调用登录接口 | 跳转首页 | 展示错误文案 | 防重复点击 |

## 5. 状态与展示规则

| 页面 | 业务状态 | 展示内容 | 可操作项 | 禁用项 | 提示文案 |
|---|---|---|---|---|---|
| 登录页 | 默认 | 输入框和登录按钮 | 输入手机号密码 | 登录按钮 | 请输入手机号 |

## 8. 待确认问题

- [ ] 错误文案是否统一？
"""


def test_missing_prototype_notes_warns_without_failing(tmp_path):
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
    assert analysis_result.prototype_notes["loaded"] is False
    assert any(
        "未发现 prototype-notes.md" in warning for warning in analysis_result.warnings
    )
    assert mvp_result.success
    assert mvp_result.prototype_notes["loaded"] is False
    assert any(
        "未发现 prototype-notes.md" in warning for warning in mvp_result.warnings
    )


def test_requirement_images_without_prototype_notes_warns(tmp_path):
    repo_root = create_repo(
        tmp_path,
        requirement="# 登录需求\n\n![登录原型](login.png)\n\n用户通过手机号密码登录。",
    )

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.prototype_notes["requirement_has_images"] is True
    assert any("包含图片引用" in warning for warning in result.warnings)


def test_existing_prototype_notes_are_loaded(tmp_path):
    repo_root = create_repo(tmp_path)
    write_file(repo_root / "prd/demo-requirement/prototype-notes.md", prototype_notes_content())

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    assert result.prototype_notes["loaded"] is True
    assert result.prototype_notes["path"] == "prd/demo-requirement/prototype-notes.md"
    assert "prd/demo-requirement/prototype-notes.md" in result.loaded_files


def test_llm_prompts_include_prototype_notes_content():
    loaded_files = {
        "prd/demo-requirement/requirement.md": "# 登录需求",
        "prd/demo-requirement/prototype-notes.md": "登录按钮置灰，成功后跳转首页。",
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

    assert "登录按钮置灰，成功后跳转首页。" in analysis_prompt.prompt
    assert "登录按钮置灰，成功后跳转首页。" in testcase_prompt.prompt


def test_testcase_generation_uses_prototype_notes_for_ui_cases(tmp_path):
    repo_root = create_repo(tmp_path)
    write_file(repo_root / "prd/demo-requirement/prototype-notes.md", prototype_notes_content())

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    testcases = result.draft_artifacts["testcases"]
    assert "原型页面入口和默认展示正确" in testcases
    assert "原型字段必填、格式和边界校验正确" in testcases
    assert "原型按钮可见、可点和禁用条件正确" in testcases
