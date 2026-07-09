from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from runtime.graph.state import QAWorkflowState
from runtime.review import ReviewDecision, ReviewIntent, process_review_gate
from runtime.review.intent_parser import parse_review_decision

ACTION_ALIASES = {
    "approve": "approve",
    "reject": "reject",
    "revise": "revise",
    "show_diff": "show_diff",
    "hold": "hold",
    "clarify": "clarify",
}
ALLOWED_REVIEW_ACTIONS = tuple(ACTION_ALIASES)
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


def _review_gate_description(state: QAWorkflowState) -> str:
    artifacts = ", ".join(_artifact_keys(state)) or "未识别候选产物"
    preview_path = _preview_path(state) or "未生成候选预览"
    return "\n".join(
        [
            "Review Gate 暂停点",
            "",
            f"- Run ID: {state.run_id or ''}",
            f"- PRD: {state.prd_path}",
            f"- 候选产物: {artifacts}",
            f"- 预览路径: {preview_path}",
            "- 可选动作: approve / reject / revise / show_diff / hold / clarify",
            "- 多产物 approve/revise 必须提供 target_artifact 或 all。",
        ]
    )


def _interrupt_payload(state: QAWorkflowState) -> dict[str, Any]:
    artifact_keys = _artifact_keys(state)
    preview_path = _preview_path(state)
    return {
        "kind": "review_gate",
        "schema_version": "v1",
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "prd_path": state.prd_path,
        "artifact_keys": artifact_keys,
        "review_status": "needs_human_review",
        "preview_path": preview_path,
        "allowed_actions": list(ALLOWED_REVIEW_ACTIONS),
        "action_request": {
            "action": "review_artifact",
            "args": {
                "run_id": state.run_id,
                "prd_path": state.prd_path,
                "artifact_keys": artifact_keys,
                "preview_path": preview_path,
            },
        },
        "config": {
            "allow_accept": True,
            "allow_ignore": True,
            "allow_respond": True,
            "allow_edit": False,
            "allowed_decisions": list(ALLOWED_REVIEW_ACTIONS),
        },
        "description": _review_gate_description(state),
    }


def _decision_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"action": str(value), "user_input": str(value)}

    decision = dict(value)
    response_type = str(decision.get("type") or "").lower()
    response_args = decision.get("args")
    response_value = decision.get("response")
    if response_type == "accept":
        return {
            **decision,
            "action": decision.get("action") or "approve",
            "user_input": decision.get("user_input") or decision.get("review_notes") or "approve",
        }
    if response_type == "ignore":
        return {
            **decision,
            "action": decision.get("action") or "hold",
            "user_input": decision.get("user_input") or decision.get("review_notes") or "hold",
        }
    if response_type in {"response", "edit"}:
        if isinstance(response_args, dict):
            return {**decision, **response_args}
        if isinstance(response_value, dict):
            return {**decision, **response_value}
        text = str(response_value or decision.get("user_input") or "")
        return {**decision, "action": decision.get("action") or "", "user_input": text}
    return decision


def _validate_target_artifact_hint(*, target_artifact: Any, artifact_keys: list[str]) -> str | None:
    target = str(target_artifact or "").strip()
    if not target:
        return None
    if target != ALL_ARTIFACTS_TARGET and target not in artifact_keys:
        return f"target_artifact 不在候选产物中: {target}"
    return None


def _keep_waiting_for_review(state: QAWorkflowState, message: str | None = None) -> None:
    if message:
        state.errors.append(message)
    state.review_status = "needs_human_review"
    state.run_status = "interrupted"
    state.next_action = "wait_for_review"


def _decision_user_input(decision: dict[str, Any]) -> str:
    return str(
        decision.get("user_input")
        or decision.get("review_notes")
        or ACTION_ALIASES.get(str(decision.get("action") or "").lower(), "")
        or decision.get("action")
        or ""
    )


def _review_intent_to_state(intent: ReviewIntent) -> tuple[str, str, str]:
    if intent == ReviewIntent.APPROVE:
        return "approved", "approved", "promote"
    if intent == ReviewIntent.REJECT:
        return "rejected", "rejected", "stop"
    if intent == ReviewIntent.REVISE:
        return "needs_changes", "needs_changes", "revise"
    return "needs_human_review", "interrupted", "wait_for_review"


def _decision_from_action(
    action: str,
    *,
    target_artifact: str | None,
    reason: str,
) -> ReviewDecision | None:
    intent_by_action = {
        "approve": ReviewIntent.APPROVE,
        "reject": ReviewIntent.REJECT,
        "revise": ReviewIntent.REVISE,
        "show_diff": ReviewIntent.SHOW_DIFF,
        "hold": ReviewIntent.HOLD,
        "clarify": ReviewIntent.CLARIFY,
    }
    intent = intent_by_action.get(action)
    if intent is None:
        return None
    return ReviewDecision(
        intent=intent,
        target_artifact=target_artifact,  # type: ignore[arg-type]
        confidence=1.0,
        reason=reason,
        revision_request=reason if intent == ReviewIntent.REVISE else None,
        requires_confirmation=intent == ReviewIntent.CLARIFY,
    )


def human_review_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    if state.errors or state.quality_errors:
        return state

    debug_preview_write = state.debug_approve_preview_write or state.approve_write
    if debug_preview_write:
        state.review_status = "write_approved"
        state.run_status = "write_approved"
        state.next_action = "promote"
        state.debug_approve_preview_write = True
        state.approve_write = True
        state.human_review = {
            "status": "write_approved",
            "decision": {
                "action": "debug_approve_preview_write",
                "source": "debug_approve_preview_write",
            },
            "reviewed_by": None,
            "review_notes": (
                "debug_approve_preview_write only writes candidate preview; "
                "it cannot confirm or promote artifacts."
            ),
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
    user_input = _decision_user_input(decision)
    if not action and not user_input:
        _keep_waiting_for_review(state, "不支持的 Review Gate action: <empty>")
        state.human_review = {
            "status": state.review_status,
            "decision": {
                "action": "",
                "target_artifact": decision.get("target_artifact"),
                "source": "langgraph_interrupt_resume",
            },
            "reviewed_by": reviewed_by,
            "review_notes": review_notes,
            "interrupt": payload,
        }
        return state
    if action and action not in ACTION_ALIASES:
        _keep_waiting_for_review(state, f"不支持的 Review Gate action: {action}")
        state.human_review = {
            "status": state.review_status,
            "decision": {
                "action": action,
                "target_artifact": decision.get("target_artifact"),
                "source": "langgraph_interrupt_resume",
            },
            "reviewed_by": reviewed_by,
            "review_notes": review_notes,
            "interrupt": payload,
        }
        return state

    artifact_keys = list(payload["artifact_keys"])
    parsed_decision = parse_review_decision(user_input)
    candidate_target = decision.get("target_artifact") or parsed_decision.target_artifact
    target_error = _validate_target_artifact_hint(
        target_artifact=candidate_target,
        artifact_keys=artifact_keys,
    )
    if target_error:
        _keep_waiting_for_review(state, target_error)
        state.human_review = {
            "status": state.review_status,
            "decision": {
                "action": action,
                "target_artifact": candidate_target,
                "source": "langgraph_interrupt_resume",
            },
            "reviewed_by": reviewed_by,
            "review_notes": review_notes,
            "interrupt": payload,
        }
        return state

    if candidate_target and parsed_decision.target_artifact != candidate_target:
        parsed_decision = parsed_decision.model_copy(update={"target_artifact": candidate_target})
    action_decision = _decision_from_action(
        action,
        target_artifact=parsed_decision.target_artifact,
        reason=review_notes or user_input or action,
    )
    if action_decision is not None and parsed_decision.intent == ReviewIntent.CLARIFY:
        parsed_decision = action_decision
    result = process_review_gate(
        repo_root=repo_root,
        prd_path=state.prd_path,
        run_id=state.run_id or "",
        user_input=user_input,
        artifact_keys=artifact_keys,
        reviewed_by=str(reviewed_by or "user"),
        decision=parsed_decision,
    )

    if result.errors:
        state.errors.extend(result.errors)
    if result.warnings:
        state.warnings.extend(result.warnings)

    next_review_status, next_run_status, next_action = _review_intent_to_state(
        result.decision.intent
    )
    if result.success and result.approved_for_promote:
        state.review_status = next_review_status
        state.run_status = next_run_status
        state.next_action = next_action
    elif result.success and result.decision.intent in {ReviewIntent.REJECT, ReviewIntent.REVISE}:
        state.review_status = next_review_status
        state.run_status = next_run_status
        state.next_action = next_action
    else:
        _keep_waiting_for_review(state)

    state.human_review = {
        "status": state.review_status,
        "decision": result.decision.model_dump(mode="json"),
        "reviewed_by": reviewed_by,
        "review_notes": review_notes or result.decision.reason,
        "interrupt": payload,
        "review_gate": {
            "approved_for_promote": result.approved_for_promote,
            "target_artifacts": result.target_artifacts,
            "status_by_artifact": result.status_by_artifact,
            "diff_paths": result.diff_paths,
        },
    }
    return state
