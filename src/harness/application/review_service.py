from __future__ import annotations

from datetime import datetime, timezone

from harness.application.ports import ArtifactReviewRepository, RunEventRepository
from harness.domain.models import ReviewDecision, ReviewIntent, RunSnapshot
from harness.domain.review import validate_review_decision

UTC = timezone.utc


class ReviewRepository(ArtifactReviewRepository, RunEventRepository):
    pass


def apply_review(
    store: ReviewRepository,
    snapshot: RunSnapshot,
    decision: ReviewDecision,
) -> RunSnapshot:
    targets = validate_review_decision(snapshot, decision)
    artifacts = [candidate.artifact for candidate in snapshot.candidates]
    if decision.intent in {ReviewIntent.HOLD, ReviewIntent.SHOW_DIFF}:
        return snapshot

    reviewed_at = datetime.now(tz=UTC).isoformat()
    if decision.intent == ReviewIntent.APPROVE:
        for artifact in targets:
            snapshot.review_status[artifact] = "approved"
        store.promote_many(snapshot, targets)
        for artifact in targets:
            snapshot.review_status[artifact] = "confirmed"
        if all(snapshot.review_status.get(artifact) == "confirmed" for artifact in artifacts):
            snapshot.status = "published"
        record_status = "confirmed"
    elif decision.intent == ReviewIntent.REJECT:
        for artifact in targets:
            snapshot.review_status[artifact] = "rejected"
        snapshot.status = "rejected"
        record_status = "rejected"
    else:
        for artifact in targets:
            snapshot.review_status[artifact] = "needs_revision"
        snapshot.status = "needs_revision"
        record_status = "needs_revision"

    for artifact in targets:
        store.write_review(
            snapshot,
            artifact,
            {
                "schema_version": "agentic-qa.harness.review-record.v2",
                "run_id": snapshot.run_id,
                "artifact": artifact,
                "status": record_status,
                "decision": decision.model_dump(mode="json"),
                "reviewed_at": reviewed_at,
            },
        )
    store.save_snapshot(snapshot)
    return snapshot
