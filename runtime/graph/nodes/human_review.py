from __future__ import annotations

from runtime.graph.state import QAWorkflowState


def human_review_node(state: QAWorkflowState) -> QAWorkflowState:
    state.record_node("human_review_node")
    if state.errors or state.quality_errors:
        return state

    state.review_status = "needs_human_review"
    if state.dry_run:
        state.warnings.append("dry-run 模式需要人工审核，不写入文件。")
    return state
