# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass

MAX_INPUT_CHARS = 12000


@dataclass(frozen=True)
class PromptBuildResult:
    prompt: str
    warnings: list[str]


def _render_file_bundle(
    loaded_files: dict[str, str],
    selected_paths: list[str],
    *,
    injected_sections: dict[str, str] | None = None,
    max_input_chars: int = MAX_INPUT_CHARS,
) -> tuple[str, list[str]]:
    sections: list[str] = []
    warnings: list[str] = []
    injected_sections = injected_sections or {}

    for path in selected_paths:
        if path in loaded_files:
            sections.append(f"## {path}\n\n{loaded_files[path]}")

    for title, content in injected_sections.items():
        if content:
            sections.append(f"## {title}\n\n{content}")

    bundle = "\n\n".join(sections)
    if len(bundle) > max_input_chars:
        bundle = bundle[:max_input_chars]
        warnings.append(f"LLM Prompt 输入超过 {max_input_chars} 字符，已截断。")
    return bundle, warnings


def build_requirement_analysis_prompt(
    loaded_files: dict[str, str],
    *,
    prd_prefix: str,
    max_input_chars: int = MAX_INPUT_CHARS,
) -> PromptBuildResult:
    selected_paths = [
        f"{prd_prefix}/requirement.md",
        f"{prd_prefix}/api-doc.md",
        "rules/requirement-analysis-rules.md",
        "skills/requirement-decomposition-skill.md",
        "skills/business-rule-extraction-skill.md",
        "knowledge/templates/requirement-analysis-template.md",
        "prompts/requirement-analysis-prompt.md",
    ]
    bundle, warnings = _render_file_bundle(
        loaded_files,
        selected_paths,
        max_input_chars=max_input_chars,
    )
    prompt = f"""请基于以下上下文生成需求分析草稿。

输出必须是 Markdown，并严格包含以下 Front Matter：

---
status: needs_human_review
artifact_type: requirement_analysis
human_review_required: true
---

必须包含且只能以这些章节作为主结构：
## 1. 需求背景与目标
## 2. 业务范围
## 3. 角色与权限
## 4. 主流程拆解
## 5. 分支流程与异常流程
## 6. 业务规则清单
## 7. 数据字段与状态流转
## 8. 接口与依赖系统
## 9. 测试范围建议
## 10. 风险点与影响面
## 11. 待确认问题
## 12. 需求到测试覆盖映射

每章必须结合 PRD 或接口文档输出具体内容；待确认问题至少 3 个且必须具体可回答。
业务规则清单、风险点与影响面、需求到测试覆盖映射不得为空或只有“待补充”。
不得编造需求；不确定内容请标记为“待确认”“待补充”或“假设”。

{bundle}
"""
    return PromptBuildResult(prompt=prompt, warnings=warnings)


def build_testcase_prompt(
    loaded_files: dict[str, str],
    *,
    prd_prefix: str,
    generated_analysis: str | None = None,
    max_input_chars: int = MAX_INPUT_CHARS,
) -> PromptBuildResult:
    selected_paths = [
        f"{prd_prefix}/requirement.md",
        f"{prd_prefix}/10-analysis/requirement-analysis.md",
        "rules/testcase-rules.md",
        "skills/test-design-skill.md",
        "skills/equivalence-partitioning-skill.md",
        "skills/boundary-value-analysis-skill.md",
        "skills/scenario-modeling-skill.md",
        "skills/state-transition-modeling-skill.md",
        "skills/risk-based-testing-skill.md",
        "knowledge/templates/testcase-template.md",
        "prompts/testcase-design-prompt.md",
    ]
    injected = {}
    if generated_analysis:
        injected["本次运行生成的需求分析草稿"] = generated_analysis
    bundle, warnings = _render_file_bundle(
        loaded_files,
        selected_paths,
        injected_sections=injected,
        max_input_chars=max_input_chars,
    )
    prompt = f"""请基于以下上下文生成测试用例草稿。

输出必须是 Markdown，并严格包含以下 Front Matter：

---
status: needs_human_review
artifact_type: testcase_draft
human_review_required: true
---

测试用例表格必须使用列：标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果。
不允许新增“用例类型”列。
简单需求不少于 15 条，中等需求不少于 30 条，复杂需求不少于 50 条；信息不足时说明原因但仍输出可评审用例。
必须覆盖主流程、关键分支、权限与角色、状态流转、必填/格式/边界、异常、重复提交/幂等、数据一致性、老数据兼容、前后端一致、接口异常/弱网/超时和回归影响。
每条用例的前置条件、步骤和预期都必须可执行、可验证。
不得生成 API/UI 自动化脚本，不得输出正式 QA 结论。

{bundle}
"""
    return PromptBuildResult(prompt=prompt, warnings=warnings)
