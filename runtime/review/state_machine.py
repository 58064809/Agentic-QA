from __future__ import annotations

from dataclasses import dataclass, field

from runtime.review.decision_schema import ReviewDecision, ReviewIntent

REVIEWABLE_STATUS = "needs_human_review"
APPROVED_STATUS = "approved"
CONFIRMED_STATUS = "confirmed"
REJECTED_STATUS = "rejected"
NEEDS_CHANGES_STATUS = "needs_changes"
ALLOWED_REVIEW_ACTIONS = {
    ReviewIntent.APPROVE,
    ReviewIntent.REJECT,
    ReviewIntent.REVISE,
}


@dataclass(frozen=True)
class ReviewStateTransition:
    allowed: bool
    next_status: str
    reason: str
    errors: list[str] = field(default_factory=list)


def validate_review_transition(
    current_status: str,
    decision: ReviewDecision,
    *,
    available_artifacts: list[str],
) -> ReviewStateTransition:
    if current_status == CONFIRMED_STATUS:
        return ReviewStateTransition(
            allowed=False,
            next_status=current_status,
            reason="confirmed 状态不允许被 Review Gate 或 LLM 覆盖",
            errors=["confirmed 状态不允许再次 approve/reject/revise。"],
        )

    if len(available_artifacts) > 1 and not decision.target_artifact:
        return ReviewStateTransition(
            allowed=False,
            next_status=current_status,
            reason="多产物审核必须明确 target_artifact",
            errors=["多产物场景下 target_artifact 不明确，必须 clarify。"],
        )

    if decision.target_artifact and decision.target_artifact not in available_artifacts:
        return ReviewStateTransition(
            allowed=False,
            next_status=current_status,
            reason="target_artifact 不在当前候选产物范围内",
            errors=[f"当前运行不包含目标产物: {decision.target_artifact}"],
        )

    if decision.intent in {ReviewIntent.CLARIFY, ReviewIntent.HOLD, ReviewIntent.SHOW_DIFF}:
        return ReviewStateTransition(
            allowed=True,
            next_status=current_status,
            reason=f"{decision.intent.value} 不改变审核状态",
        )

    if decision.requires_confirmation:
        return ReviewStateTransition(
            allowed=False,
            next_status=current_status,
            reason="ReviewDecision 需要二次确认",
            errors=["低置信度或安全规则要求二次确认，不能直接流转。"],
        )

    if decision.intent in ALLOWED_REVIEW_ACTIONS and current_status != REVIEWABLE_STATUS:
        return ReviewStateTransition(
            allowed=False,
            next_status=current_status,
            reason="只有 needs_human_review 状态允许 approve/reject/revise",
            errors=[
                f"当前状态 {current_status} 不允许执行 {decision.intent.value}，"
                "只有 needs_human_review 可以审核。"
            ],
        )

    if decision.intent == ReviewIntent.APPROVE:
        return ReviewStateTransition(True, APPROVED_STATUS, "审核通过，等待确定性 promote")
    if decision.intent == ReviewIntent.REJECT:
        return ReviewStateTransition(True, REJECTED_STATUS, "审核驳回")
    if decision.intent == ReviewIntent.REVISE:
        return ReviewStateTransition(True, NEEDS_CHANGES_STATUS, "审核要求修订")

    return ReviewStateTransition(
        allowed=False,
        next_status=current_status,
        reason="未知 ReviewIntent",
        errors=[f"不支持的 ReviewIntent: {decision.intent}"],
    )


def validate_promote_transition(current_status: str) -> ReviewStateTransition:
    if current_status == APPROVED_STATUS:
        return ReviewStateTransition(True, CONFIRMED_STATUS, "approved 允许确定性 promote")
    return ReviewStateTransition(
        allowed=False,
        next_status=current_status,
        reason="只有 approved 状态允许 promote",
        errors=[f"当前状态 {current_status} 不允许 promote，必须先 approved。"],
    )
