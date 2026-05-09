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

必须包含章节：需求概述、业务规则、流程拆解、角色与权限、数据与状态、异常与边界、风险点、待确认问题。
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
不得生成 API/UI 自动化脚本，不得输出正式 QA 结论。

{bundle}
"""
    return PromptBuildResult(prompt=prompt, warnings=warnings)
