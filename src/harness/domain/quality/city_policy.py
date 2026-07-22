from __future__ import annotations

from harness.domain.quality.city_opening_rewards import (
    _deterministically_enrich_artifact,
    _quality_check,
)
from harness.domain.quality.models import PolicyResult, QualityContext, QualityIssue


class CityOpeningRewardsPolicy:
    name = "city-opening-rewards"
    version = "1.0.0"

    def evaluate(self, context: QualityContext, content: str) -> PolicyResult:
        enriched, audit = _deterministically_enrich_artifact(
            context.artifact,
            content,
            source_corpus=context.source_corpus,
        )
        try:
            _quality_check(context.artifact, enriched, source_corpus=context.source_corpus)
        except ValueError as exc:
            issue = QualityIssue(
                policy=self.name,
                version=self.version,
                code="domain_quality_gate",
                message=str(exc),
            )
            return PolicyResult(content=enriched, issues=(issue,))
        actions = tuple(str(item) for item in (audit or {}).get("rules", []))
        return PolicyResult(content=enriched, actions=actions)
