from __future__ import annotations

from harness.domain.models import ReviewDecision, ReviewIntent, RunSnapshot


def validate_review_decision(snapshot: RunSnapshot, decision: ReviewDecision) -> list[str]:
    if snapshot.status not in {"needs_human_review", "partial", "on_hold"}:
        raise ValueError(f"run 当前状态不可审核: {snapshot.status}")
    artifacts = [candidate.artifact for candidate in snapshot.candidates]
    if len(artifacts) > 1 and not decision.target_artifact:
        raise ValueError("多候选审核必须指定单个 artifact 或 all")
    target = decision.target_artifact or (artifacts[0] if len(artifacts) == 1 else None)
    if target == "all":
        targets = artifacts
    elif target in artifacts:
        targets = [target]
    else:
        raise ValueError(f"target_artifact 不在本次候选中: {target}")
    if decision.intent == ReviewIntent.APPROVE:
        if {item.artifact for item in decision.versions} != set(targets):
            raise ValueError("approve 必须为每个目标 artifact 提供且仅提供一个强类型版本")
        for artifact in targets:
            candidate = next(item for item in snapshot.candidates if item.artifact == artifact)
            if candidate.status == "partial" or candidate.partial is not False:
                raise PermissionError(f"partial candidate 不可发布: {artifact}")
    return targets
