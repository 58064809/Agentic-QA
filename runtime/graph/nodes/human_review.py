from __future__ import annotations

from runtime.graph.state import QAWorkflowState


def human_review_node(state: QAWorkflowState) -> QAWorkflowState:
    state.record_node("human_review_node")
    if state.errors or state.quality_errors:
        return state

    if state.approve_write:
        state.review_status = "write_approved"
        state.run_status = "write_approved"
        state.human_review = {
            "status": "write_approved",
            "decision": {
                "action": "approve_write",
                "source": "approve_write",
            },
            "reviewed_by": None,
            "review_notes": "approve_write 已授权 Runtime 写入草稿",
            "interrupt": None,
        }
        return state

    state.review_status = "needs_human_review"
    state.run_status = "waiting_review"
    state.human_review = {
        "status": "needs_human_review",
        "decision": {
            "action": "wait_for_review",
            "source": "default",
        },
        "reviewed_by": None,
        "review_notes": "候选产物已生成，等待人工确认后才能发布正式产物。",
        "interrupt": None,
    }
    return state
