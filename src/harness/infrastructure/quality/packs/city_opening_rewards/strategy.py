from __future__ import annotations

import difflib

from harness.application.quality import (
    QualityComponentConfiguration,
    QualityContext,
    QualityIssue,
    StrategyRequirements,
    StrategyResult,
)
from harness.infrastructure.quality.packs.city_opening_rewards.parser import source_corpus
from harness.infrastructure.quality.packs.city_opening_rewards.remediation import (
    _deterministically_enrich_artifact,
)
from harness.infrastructure.quality.packs.city_opening_rewards.validators import _quality_check


class CityOpeningRewardsStrategy:
    name = "city-opening-rewards"
    version = "2.1.0"
    requirements = StrategyRequirements(requires_sources=True, requires_complete_sources=True)
    configuration = QualityComponentConfiguration()

    def evaluate(self, context: QualityContext, content: str) -> StrategyResult:
        corpus = source_corpus(context.source_bundle)
        enriched, audit = _deterministically_enrich_artifact(
            context.artifact,
            content,
            source_corpus=corpus,
        )
        remediation = None
        if enriched != content:
            remediation = "".join(
                difflib.unified_diff(
                    content.splitlines(keepends=True),
                    enriched.splitlines(keepends=True),
                    fromfile="raw",
                    tofile="suggested-remediation",
                )
            )
        try:
            _quality_check(context.artifact, content, source_corpus=corpus)
        except ValueError as exc:
            return StrategyResult(
                issues=(
                    QualityIssue(
                        policy=self.name,
                        version=self.version,
                        code="domain_quality_gate",
                        message=str(exc),
                    ),
                ),
                actions=tuple(str(item) for item in (audit or {}).get("rules", [])),
                remediation_patch=remediation,
            )
        return StrategyResult(
            actions=tuple(str(item) for item in (audit or {}).get("rules", [])),
            remediation_patch=remediation,
        )
