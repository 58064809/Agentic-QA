from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runtime.llm.config import OpenAICompatibleConfig
from runtime.review.decision_schema import ReviewDecision, ReviewIntent
from runtime.review.intent_parser import parse_review_decision
from runtime.review.state_machine import (
    APPROVED_STATUS,
    validate_promote_transition,
    validate_review_transition,
)
from runtime.workspace import (
    ARTIFACT_SPECS,
    PRDWorkspace,
    now_iso,
    read_yaml_mapping,
    write_yaml_mapping,
)


@dataclass(frozen=True)
class ReviewGateResult:
    decision: ReviewDecision
    target_artifacts: list[str]
    status_by_artifact: dict[str, str]
    next_status: str
    approved_for_promote: bool = False
    diff_paths: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors


def _read_review(workspace: PRDWorkspace, artifact_key: str) -> dict[str, Any]:
    path = workspace.review_path(artifact_key)
    if not path.is_file():
        return {
            "artifact": ARTIFACT_SPECS[artifact_key]["current_path"],
            "artifact_type": ARTIFACT_SPECS[artifact_key]["artifact_type"],
            "status": "needs_human_review",
        }
    return read_yaml_mapping(path)


def _target_artifacts(decision: ReviewDecision, artifact_keys: list[str]) -> list[str]:
    if decision.target_artifact == "all":
        return list(artifact_keys)
    if decision.target_artifact:
        return [decision.target_artifact] if decision.target_artifact in artifact_keys else []
    if len(artifact_keys) == 1:
        return list(artifact_keys)
    return []


def _normalize_decision_target(
    decision: ReviewDecision, artifact_keys: list[str]
) -> ReviewDecision:
    if decision.target_artifact:
        return decision
    if len(artifact_keys) == 1:
        return decision.model_copy(update={"target_artifact": artifact_keys[0]})
    if decision.intent in {
        ReviewIntent.REJECT,
        ReviewIntent.SHOW_DIFF,
        ReviewIntent.HOLD,
        ReviewIntent.CLARIFY,
    }:
        return decision.model_copy(update={"target_artifact": "all"})
    return decision


def _write_review_decision(
    workspace: PRDWorkspace,
    artifact_key: str,
    review: dict[str, Any],
    decision: ReviewDecision,
    *,
    next_status: str,
    run_id: str,
    reviewed_by: str,
    source_message: str,
) -> None:
    timestamp = now_iso()
    review["status"] = next_status
    review["decision"] = decision.intent.value
    review["reviewer"] = reviewed_by
    review["reviewed_at"] = timestamp
    review["run_id"] = run_id
    review["source_message"] = source_message
    review["review_decision"] = decision.model_dump(mode="json")
    if decision.revision_request:
        changes = review.get("required_changes")
        if not isinstance(changes, list):
            changes = []
        changes.append(decision.revision_request)
        review["required_changes"] = changes
    write_yaml_mapping(workspace.review_path(artifact_key), review)


def process_review_gate(
    *,
    repo_root: Path,
    prd_path: str | Path,
    run_id: str,
    user_input: str,
    artifact_keys: list[str],
    reviewed_by: str = "user",
    config: OpenAICompatibleConfig | None = None,
    decision: ReviewDecision | None = None,
) -> ReviewGateResult:
    workspace = PRDWorkspace(repo_root / Path(prd_path))
    available_artifacts = [key for key in artifact_keys if key in ARTIFACT_SPECS]
    if not available_artifacts:
        return ReviewGateResult(
            decision=ReviewDecision(
                intent=ReviewIntent.CLARIFY,
                confidence=1.0,
                reason="未识别目标产物",
                requires_confirmation=True,
            ),
            target_artifacts=[],
            status_by_artifact={},
            next_status="",
            errors=["未识别目标产物。"],
        )

    parsed = _normalize_decision_target(
        decision or parse_review_decision(user_input, config=config),
        available_artifacts,
    )
    target_artifacts = _target_artifacts(parsed, available_artifacts)
    if parsed.intent == ReviewIntent.SHOW_DIFF:
        diff_path = workspace.diff_path(run_id)
        diff_paths = {
            key: diff_path.relative_to(repo_root).as_posix()
            for key in (target_artifacts or available_artifacts)
            if diff_path.is_file()
        }
        return ReviewGateResult(
            decision=parsed,
            target_artifacts=target_artifacts or available_artifacts,
            status_by_artifact={
                key: str(_read_review(workspace, key).get("status", "needs_human_review"))
                for key in available_artifacts
            },
            next_status="",
            diff_paths=diff_paths,
        )

    if not target_artifacts:
        clarify = parsed.model_copy(
            update={
                "intent": ReviewIntent.CLARIFY,
                "requires_confirmation": True,
                "reason": "多产物场景下 target_artifact 不明确",
            }
        )
        return ReviewGateResult(
            decision=clarify,
            target_artifacts=[],
            status_by_artifact={
                key: str(_read_review(workspace, key).get("status", "needs_human_review"))
                for key in available_artifacts
            },
            next_status="",
            errors=["多产物场景下 target_artifact 不明确，必须 clarify。"],
        )

    status_by_artifact: dict[str, str] = {}
    errors: list[str] = []
    next_status = ""
    for artifact_key in target_artifacts:
        review = _read_review(workspace, artifact_key)
        current_status = str(review.get("status") or "needs_human_review")
        transition_decision = (
            parsed.model_copy(update={"target_artifact": artifact_key})
            if parsed.target_artifact == "all"
            else parsed
        )
        transition = validate_review_transition(
            current_status,
            transition_decision,
            available_artifacts=available_artifacts,
        )
        if not transition.allowed:
            errors.extend(transition.errors)
            status_by_artifact[artifact_key] = current_status
            next_status = transition.next_status
            continue

        next_status = transition.next_status
        if parsed.intent in {ReviewIntent.APPROVE, ReviewIntent.REJECT, ReviewIntent.REVISE}:
            _write_review_decision(
                workspace,
                artifact_key,
                review,
                transition_decision,
                next_status=next_status,
                run_id=run_id,
                reviewed_by=reviewed_by,
                source_message=user_input,
            )
        status_by_artifact[artifact_key] = next_status

    approved_for_promote = False
    if not errors and parsed.intent == ReviewIntent.APPROVE:
        promote_checks = [
            validate_promote_transition(status_by_artifact[key]) for key in target_artifacts
        ]
        errors.extend(error for check in promote_checks for error in check.errors)
        approved_for_promote = not errors and all(
            status_by_artifact[key] == APPROVED_STATUS for key in target_artifacts
        )

    return ReviewGateResult(
        decision=parsed,
        target_artifacts=target_artifacts,
        status_by_artifact=status_by_artifact,
        next_status=next_status,
        approved_for_promote=approved_for_promote,
        errors=errors,
    )
