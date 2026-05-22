from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from runtime.graph.state import QAWorkflowState


def _decision_action(decision: Any) -> str:
    if isinstance(decision, dict):
        return str(decision.get("action", "")).strip().lower()
    return str(decision).strip().lower()


def human_review_node(state: QAWorkflowState) -> QAWorkflowState:
    state.record_node("human_review_node")
    if state.errors or state.quality_errors:
        return state

    decision = interrupt(
        {
            "run_id": state.run_id,
            "thread_id": state.thread_id,
            "task_type": state.task_type,
            "output_path": state.output_path,
            "output_paths": state.output_paths,
            "message": "请人工审核产物草稿后执行 approve 或 reject。",
        }
    )
    action = _decision_action(decision)
    if action == "approve":
        state.review_status = "approved"
        state.run_status = "approved"
        state.human_review = {
            "status": "approved",
            "decision": decision,
            "reviewed_by": decision.get("reviewed_by") if isinstance(decision, dict) else None,
            "review_notes": decision.get("review_notes") if isinstance(decision, dict) else None,
            "interrupt": None,
        }
        if state.dry_run:
            state.warnings.append("dry-run 模式已通过人工审核，但仍不写入文件。")
        return state

    if action == "reject":
        state.review_status = "rejected"
        state.run_status = "rejected"
        state.human_review = {
            "status": "rejected",
            "decision": decision,
            "reviewed_by": decision.get("reviewed_by") if isinstance(decision, dict) else None,
            "review_notes": decision.get("review_notes") if isinstance(decision, dict) else None,
            "interrupt": None,
        }
        state.warnings.append("人工审核已拒绝，产物未写入。")
        return state

    state.review_status = "needs_human_review"
    state.run_status = "interrupted"
    state.human_review = {
        "status": "needs_human_review",
        "decision": decision,
        "reviewed_by": None,
        "review_notes": None,
        "interrupt": None,
    }
    state.warnings.append("未知人工审核动作，产物未写入。")
    return state
