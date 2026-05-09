from __future__ import annotations

from runtime.graph.state import QAWorkflowState


def testcase_generation_node(state: QAWorkflowState) -> QAWorkflowState:
    state.record_node("testcase_generation_node")
    if state.errors:
        return state

    source_lines = "\n".join(f"- `{path}`" for path in sorted(state.loaded_files))
    mode = "approve-write" if state.approve_write else "dry-run"
    state.draft_artifact = f"""---
status: needs_human_review
human_review_required: true
artifact_type: testcase_draft
generated_by: Runtime Skeleton
---

# 测试用例草稿

> 状态：needs_human_review
> 来源：Runtime Skeleton {mode}
> 注意：当前内容为 Runtime 最小骨架生成，不代表最终 AI 生成质量。

## 来源文件

{source_lines}

| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|
| 待补充：基于需求主流程生成 | P0 | 待人工确认 | 待接入 LangChain 后生成 | 待人工确认 |

## 待人工确认

- [ ] 需求理解是否准确。
- [ ] 后续 LangChain / LangGraph 接入后生成的测试用例是否可接受。
- [ ] 是否允许继续生成 API/UI 自动化脚本草稿。
"""
    return state
