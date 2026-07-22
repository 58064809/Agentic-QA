from __future__ import annotations

from datetime import datetime, timezone

from harness.application.ports import ArtifactReviewRepository, RunEventRepository
from harness.application.quality import QualityReport
from harness.domain.models import (
    ApprovedArtifactVersion,
    ReviewDecision,
    ReviewIntent,
    RunSnapshot,
)
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
    approved_by_artifact: dict[str, ApprovedArtifactVersion] = {}
    if decision.intent == ReviewIntent.APPROVE:
        requested = {item.artifact: item for item in decision.versions}
        for artifact in targets:
            candidate = next(item for item in snapshot.candidates if item.artifact == artifact)
            if not candidate.assessment_key or not candidate.quality_report_sha256:
                raise PermissionError("旧 candidate 缺少质量 provenance，不能批准")
            selected = requested[artifact]
            version = next(
                (
                    item
                    for item in candidate.versions
                    if item.variant == selected.variant
                    and item.content_sha256 == selected.content_sha256
                ),
                None,
            )
            if (
                version is None
                or selected.assessment_key != candidate.assessment_key
                or selected.quality_report_sha256 != candidate.quality_report_sha256
            ):
                raise ValueError("审核选择与 candidate manifest 不匹配")
            report = store.load_quality_report(candidate)
            if not isinstance(report, QualityReport) or not report.verdict_for(selected.variant):
                raise PermissionError(f"所选版本未通过质量门: {artifact}/{selected.variant.value}")
            approved_by_artifact[artifact] = ApprovedArtifactVersion(
                **selected.model_dump(), path=version.path
            )
        store.promote_many(snapshot, list(approved_by_artifact.values()))
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
                "approved_version": (
                    approved_by_artifact[artifact].model_dump(mode="json")
                    if artifact in approved_by_artifact
                    else None
                ),
                "reviewed_at": reviewed_at,
            },
        )
    store.save_snapshot(snapshot)
    return snapshot
