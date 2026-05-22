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
                "source": "--approve-write",
            },
            "reviewed_by": None,
            "review_notes": "--approve-write 已授权 Runtime 写入草稿",
            "interrupt": None,
        }
        return state

    state.review_status = "needs_human_review"
    state.run_status = "dry_run"
    state.human_review = {
        "status": "needs_human_review",
        "decision": {
            "action": "dry_run",
            "source": "default",
        },
        "reviewed_by": None,
        "review_notes": "dry-run 未写入文件；需要写入请传 --approve-write。",
        "interrupt": None,
    }
    state.warnings.append("dry-run 模式不写入文件；需要写入请显式传入 --approve-write。")
    return state
