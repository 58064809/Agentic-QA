from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from runtime.graph.state import QAWorkflowState

ALLOWED_REVIEW_ACTIONS = {"approve", "reject", "revise"}


def _artifact_keys(state: QAWorkflowState) -> list[str]:
    if state.output_paths:
        return sorted(state.output_paths)
    return sorted(
        str(artifact["name"])
        for artifact in state.artifacts
        if isinstance(artifact.get("name"), str)
    )


def _preview_path(state: QAWorkflowState) -> str | None:
    if state.output_path:
        return state.output_path
    if state.output_paths:
        return next(iter(state.output_paths.values()))
    return None


def _interrupt_payload(state: QAWorkflowState) -> dict[str, Any]:
    return {
        "run_id": state.run_id,
        "prd_path": state.prd_path,
        "artifact_keys": _artifact_keys(state),
        "review_status": "needs_human_review",
        "preview_path": _preview_path(state),
        "allowed_actions": ["approve", "reject", "revise"],
    }


def _decision_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {"action": str(value)}


def human_review_node(state: QAWorkflowState) -> QAWorkflowState:
    state.record_node("human_review_node")
    if state.errors or state.quality_errors:
        return state

    if state.approve_write:
        state.review_status = "write_approved"
        state.run_status = "write_approved"
        state.next_action = "promote"
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
    state.run_status = "interrupted"
    state.next_action = "wait_for_review"
    payload = _interrupt_payload(state)
    state.human_review = {
        "status": "needs_human_review",
        "decision": {
            "action": "wait_for_review",
            "source": "default",
        },
        "reviewed_by": None,
        "review_notes": "候选产物已生成，等待人工确认后才能发布正式产物。",
        "interrupt": payload,
    }

    decision = _decision_mapping(interrupt(payload))
    action = str(decision.get("action") or "").lower()
    reviewed_by = decision.get("reviewed_by")
    review_notes = decision.get("review_notes")
    target_artifact = decision.get("target_artifact")
    if action not in ALLOWED_REVIEW_ACTIONS:
        state.errors.append(f"不支持的 Review Gate action: {action or '<empty>'}")
        state.next_action = "stop"
        return state

    if action == "approve":
        state.review_status = "approved"
        state.run_status = "approved"
        state.next_action = "promote"
    elif action == "reject":
        state.review_status = "rejected"
        state.run_status = "rejected"
        state.next_action = "stop"
    else:
        state.review_status = "needs_changes"
        state.run_status = "needs_changes"
        state.next_action = "revise"

    state.human_review = {
        "status": state.review_status,
        "decision": {
            "action": action,
            "target_artifact": target_artifact,
            "source": "langgraph_interrupt_resume",
        },
        "reviewed_by": reviewed_by,
        "review_notes": review_notes,
        "interrupt": payload,
    }
    return state
