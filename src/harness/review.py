from __future__ import annotations

from datetime import UTC, datetime

from harness.contracts import ReviewDecision, ReviewIntent, RunSnapshot
from harness.store import WorkspaceStore


def apply_review(
    store: WorkspaceStore,
    snapshot: RunSnapshot,
    decision: ReviewDecision,
) -> RunSnapshot:
    if snapshot.status not in {"needs_human_review", "partial"}:
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

    if decision.intent in {ReviewIntent.HOLD, ReviewIntent.SHOW_DIFF}:
        return snapshot

    if decision.intent == ReviewIntent.APPROVE:
        workspace = store.require_workspace(snapshot.workspace)
        candidate_root = (workspace / "candidates" / snapshot.run_id).resolve()
        for artifact in targets:
            candidate = next(item for item in snapshot.candidates if item.artifact == artifact)
            source = (store.repo_root / candidate.path).resolve()
            if source.parent != candidate_root or not source.is_file():
                raise ValueError(f"候选路径越界或不存在: {artifact}")

    next_status = {
        ReviewIntent.APPROVE: "approved",
        ReviewIntent.REJECT: "rejected",
        ReviewIntent.REVISE: "needs_revision",
    }[decision.intent]
    reviewed_at = datetime.now(tz=UTC).isoformat()
    for artifact in targets:
        snapshot.review_status[artifact] = next_status
        store.write_review(
            snapshot,
            artifact,
            {
                "schema_version": "agentic-qa.harness.review-record.v1",
                "run_id": snapshot.run_id,
                "artifact": artifact,
                "status": next_status,
                "decision": decision.model_dump(mode="json"),
                "reviewed_at": reviewed_at,
            },
        )

    if decision.intent == ReviewIntent.APPROVE:
        for artifact in targets:
            store.promote(snapshot, artifact)
            snapshot.review_status[artifact] = "confirmed"
        if all(snapshot.review_status.get(artifact) == "confirmed" for artifact in artifacts):
            snapshot.status = "published"
    elif decision.intent == ReviewIntent.REJECT:
        snapshot.status = "rejected"
    else:
        snapshot.status = "needs_revision"
    store.save_snapshot(snapshot)
    return snapshot
