from __future__ import annotations

from runtime.graph.nodes.mvp_context_loader import (
    TASK_ANALYSIS,
    TASK_MVP,
    TASK_TESTCASE_GENERATION,
)
from runtime.graph.state import QAWorkflowState
from runtime.llm.config import API_KEY_ENV, OpenAICompatibleConfig
from runtime.llm.openai_compatible import OpenAICompatibleAdapter
from runtime.llm.prompt_builder import (
    build_requirement_analysis_prompt,
    build_testcase_prompt,
)


def _prd_prefix(state: QAWorkflowState) -> str:
    return state.prd_path.replace("\\", "/").rstrip("/")


def _upsert_artifact(
    state: QAWorkflowState,
    *,
    name: str,
    artifact_type: str,
    output_path: str,
    wrote_file: bool = False,
) -> None:
    artifact = {
        "name": name,
        "artifact_type": artifact_type,
        "output_path": output_path,
        "status": "needs_human_review",
        "wrote_file": wrote_file,
    }
    state.artifacts = [
        existing for existing in state.artifacts if existing.get("name") != name
    ]
    state.artifacts.append(artifact)


def _append_llm_error(state: QAWorkflowState, message: str) -> None:
    errors = list(state.llm.get("errors", []))
    errors.append(message)
    state.llm["errors"] = errors


def _generate_with_optional_llm(
    state: QAWorkflowState,
    *,
    prompt: str,
    fallback: str,
) -> str:
    config = OpenAICompatibleConfig.from_env()
    state.llm["enabled"] = state.use_llm
    state.llm["provider"] = "openai_compatible"
    state.llm["base_url"] = config.base_url
    state.llm["model"] = config.model

    if not state.use_llm:
        return fallback

    if not config.has_api_key:
        message = (
            f"已请求 LLM，但未设置 {API_KEY_ENV} 环境变量，已降级为 Skeleton 生成。"
        )
        state.warnings.append(message)
        _append_llm_error(state, message)
        return fallback

    calls = int(state.llm.get("calls", 0) or 0)
    if calls >= state.max_llm_calls:
        message = "LLM 调用次数已达到本次 run 上限，已降级为 Skeleton 生成。"
        state.warnings.append(message)
        _append_llm_error(state, message)
        return fallback

    state.llm["calls"] = calls + 1
    try:
        content = OpenAICompatibleAdapter(config).generate_text(prompt)
    except Exception as exc:  # noqa: BLE001 - external SDK failures must degrade.
        message = f"LLM 调用失败，已降级为 Skeleton 生成: {exc}"
        state.warnings.append(message)
        _append_llm_error(state, message)
        return fallback

    state.llm["used"] = True
    return content


def render_requirement_analysis_skeleton(state: QAWorkflowState) -> str:
    source_lines = "\n".join(f"- `{path}`" for path in sorted(state.loaded_files))
    return f"""---
status: needs_human_review
artifact_type: requirement_analysis
human_review_required: true
generated_by: Runtime MVP Skeleton
---

# 需求分析草稿

> 状态：needs_human_review
> 来源：Runtime MVP Skeleton
> 注意：当前内容为可审核草稿，不代表正式需求结论。

## 需求概述

- 待人工确认：已读取 PRD 工作区材料，并基于现有上下文生成需求分析草稿。

## 业务规则

- 待补充：请结合 `requirement.md` 与可选 `api-doc.md` 确认可测试业务规则。

## 流程拆解

- 待补充：主流程、替代流程和异常流程需要人工审核确认。

## 角色与权限

- 待确认：当前 PRD 是否涉及不同角色、权限边界或访问控制。

## 数据与状态

- 待确认：输入数据、输出数据、状态变化、过期和恢复规则。

## 异常与边界

- 待补充：异常输入、边界条件、失败提示和安全提示。

## 风险点

- 待确认：安全、权限、状态一致性和错误提示是否存在高风险场景。

## 待确认问题

- [ ] 需求理解是否准确。
- [ ] 隐含业务规则是否需要补充。
- [ ] 风险优先级是否需要调整。

## 来源文件

{source_lines}
"""


def render_testcase_skeleton(state: QAWorkflowState) -> str:
    source_lines = "\n".join(f"- `{path}`" for path in sorted(state.loaded_files))
    analysis_source = (
        "本次运行生成的需求分析草稿"
        if state.draft_artifacts.get("requirement_analysis")
        else "PRD 工作区现有材料"
    )
    return f"""---
status: needs_human_review
artifact_type: testcase_draft
human_review_required: true
generated_by: Runtime MVP Skeleton
---

# 测试用例草稿

> 状态：needs_human_review
> 来源：Runtime MVP Skeleton
> 分析依据：{analysis_source}
> 注意：当前内容为可审核草稿，不代表正式 QA 结论。

| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|
| 主流程验证 | P0 | 待确认账号和数据 | 1. 按主流程操作<br>2. 观察响应 | 结果符合需求 |
| 异常输入验证 | P1 | 待确认异常数据 | 1. 输入不合法数据<br>2. 提交请求 | 错误提示符合需求 |
| 待补充：边界条件验证 | P1 | 待确认边界值 | 1. 使用边界值操作<br>2. 校验响应 | 边界行为符合需求 |

## 来源文件

{source_lines}

## 待人工确认

- [ ] 测试用例是否覆盖主流程、异常流程和边界条件。
- [ ] 前置条件、测试数据和预期结果是否准确。
- [ ] 是否允许后续生成 API/UI 自动化脚本草稿。
"""


def requirement_analysis_generation_node(state: QAWorkflowState) -> QAWorkflowState:
    if state.task_type not in {TASK_ANALYSIS, TASK_MVP}:
        return state
    state.record_node("requirement_analysis_generation_node")
    if state.errors:
        return state

    prompt = build_requirement_analysis_prompt(
        state.loaded_files,
        prd_prefix=_prd_prefix(state),
    )
    state.warnings.extend(prompt.warnings)
    artifact = _generate_with_optional_llm(
        state,
        prompt=prompt.prompt,
        fallback=render_requirement_analysis_skeleton(state),
    )
    state.draft_artifacts["requirement_analysis"] = artifact
    state.draft_artifact = artifact
    output_path = state.output_paths.get("requirement_analysis")
    if output_path:
        state.output_path = output_path if state.task_type == TASK_ANALYSIS else state.output_path
        _upsert_artifact(
            state,
            name="requirement_analysis",
            artifact_type="requirement_analysis",
            output_path=output_path,
        )
    return state


def testcase_generation_mvp_node(state: QAWorkflowState) -> QAWorkflowState:
    if state.task_type not in {TASK_TESTCASE_GENERATION, TASK_MVP}:
        return state
    state.record_node("testcase_generation_node")
    if state.errors:
        return state

    prompt = build_testcase_prompt(
        state.loaded_files,
        prd_prefix=_prd_prefix(state),
        generated_analysis=state.draft_artifacts.get("requirement_analysis"),
    )
    state.warnings.extend(prompt.warnings)
    artifact = _generate_with_optional_llm(
        state,
        prompt=prompt.prompt,
        fallback=render_testcase_skeleton(state),
    )
    state.draft_artifacts["testcases"] = artifact
    state.draft_artifact = artifact
    output_path = state.output_paths.get("testcases")
    if output_path:
        if state.task_type == TASK_TESTCASE_GENERATION:
            state.output_path = output_path
        _upsert_artifact(
            state,
            name="testcases",
            artifact_type="testcase_draft",
            output_path=output_path,
        )
    return state
