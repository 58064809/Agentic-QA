from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from runtime.graph.state import QAWorkflowState

ALLOWED_REVIEW_ACTIONS = {"approve", "reject", "revise"}
ALL_ARTIFACTS_TARGET = "all"


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


def _normalize_target_artifact(
    *,
    action: str,
    target_artifact: Any,
    artifact_keys: list[str],
) -> tuple[str | None, str | None]:
    target = str(target_artifact or "").strip()
    if len(artifact_keys) == 1:
        if not target:
            return artifact_keys[0], None
        if target in {artifact_keys[0], ALL_ARTIFACTS_TARGET}:
            return target, None
        return None, f"target_artifact 不在候选产物中: {target}"

    if action == "reject" and not target:
        return ALL_ARTIFACTS_TARGET, None

    if not target:
        return None, "多产物 Review Gate 需要明确 target_artifact 或 all。"
    if target == ALL_ARTIFACTS_TARGET or target in artifact_keys:
        return target, None
    return None, f"target_artifact 不在候选产物中: {target}"


def _keep_waiting_for_review(
    state: QAWorkflowState,
    payload: dict[str, Any],
    decision: dict[str, Any],
    message: str,
) -> QAWorkflowState:
    state.errors.append(message)
    state.review_status = "needs_human_review"
    state.run_status = "interrupted"
    state.next_action = "wait_for_review"
    state.human_review = {
        "status": "needs_human_review",
        "decision": {
            "action": str(decision.get("action") or ""),
            "target_artifact": decision.get("target_artifact"),
            "source": "langgraph_interrupt_resume",
        },
        "reviewed_by": decision.get("reviewed_by"),
        "review_notes": decision.get("review_notes"),
        "interrupt": payload,
    }
    return state


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
    if action not in ALLOWED_REVIEW_ACTIONS:
        return _keep_waiting_for_review(
            state,
            payload,
            decision,
            f"不支持的 Review Gate action: {action or '<empty>'}",
        )

    artifact_keys = list(payload["artifact_keys"])
    target_artifact, target_error = _normalize_target_artifact(
        action=action,
        target_artifact=decision.get("target_artifact"),
        artifact_keys=artifact_keys,
    )
    if target_error:
        return _keep_waiting_for_review(state, payload, decision, target_error)

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
