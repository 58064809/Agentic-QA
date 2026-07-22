from __future__ import annotations

import difflib
import hashlib
import json
from typing import Any

from harness.application.quality import (
    ArtifactVariant,
    CandidateAssessment,
    NormalizationAudit,
    NormalizationStatus,
    QualityContext,
    QualityIssue,
    QualityReport,
    StrategyAudit,
    VariantAssessment,
)
from harness.application.source import SourceCompleteness
from harness.infrastructure.quality.normalization import apply_safe_normalization
from harness.infrastructure.quality.registry import QualityStrategyRegistry

PIPELINE_VERSION = "2.0.0"


def sha256_text(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class CandidateAssessmentService:
    def __init__(self, registry: QualityStrategyRegistry) -> None:
        self.registry = registry

    def assessment_key(
        self,
        *,
        context: QualityContext,
        content: str,
        media_type: str,
        strategy_names: list[str],
    ) -> str:
        strategies = self.registry.require(strategy_names)
        return canonical_sha256(
            {
                "schema": "agentic-qa.harness.assessment-input.v2",
                "pipeline_version": PIPELINE_VERSION,
                "workspace_id": context.workspace_id,
                "run_id": context.run_id,
                "artifact": context.artifact,
                "raw": {"media_type": media_type, "sha256": sha256_text(content)},
                "source_bundle_hash": context.source_bundle.bundle_hash,
                "normalizers": [
                    {
                        "name": item.name,
                        "version": item.version,
                        "configuration_sha256": canonical_sha256(
                            item.configuration.model_dump(mode="json")
                        ),
                    }
                    for item in self.registry.normalizers()
                ],
                "strategies": [
                    {
                        "name": item.name,
                        "version": item.version,
                        "configuration_sha256": canonical_sha256(
                            item.configuration.model_dump(mode="json")
                        ),
                        "requirements": item.requirements.model_dump(mode="json"),
                    }
                    for item in strategies
                ],
            }
        )

    def assess(
        self,
        *,
        context: QualityContext,
        content: str,
        media_type: str,
        strategy_names: list[str],
    ) -> CandidateAssessment:
        strategies = self.registry.require(strategy_names)
        key = self.assessment_key(
            context=context,
            content=content,
            media_type=media_type,
            strategy_names=strategy_names,
        )
        normalized = content
        normalization_error: str | None = None
        normalizers = self.registry.normalizers()
        for normalizer in self.registry.normalizers():
            try:
                normalized = apply_safe_normalization(
                    normalized, normalizer.propose(context, normalized)
                )
            except Exception as exc:
                normalized = content
                normalization_error = f"{normalizer.name}: {type(exc).__name__}: {exc}"
                break
        normalized_content = (
            normalized if normalization_error is None and normalized != content else None
        )
        normalization_patch = None
        if normalized_content is not None:
            normalization_patch = "".join(
                difflib.unified_diff(
                    content.splitlines(keepends=True),
                    normalized_content.splitlines(keepends=True),
                    fromfile="raw",
                    tofile="normalized",
                )
            )
        variants: list[VariantAssessment] = []
        remediation_patches: list[str] = []
        contents: list[tuple[ArtifactVariant, str]] = [(ArtifactVariant.RAW, content)]
        if normalized_content is not None:
            contents.append((ArtifactVariant.NORMALIZED, normalized_content))
        for variant, variant_content in contents:
            audits: list[StrategyAudit] = []
            issues = self._source_issues(context, strategies)
            for strategy in strategies:
                result = strategy.evaluate(context, variant_content)
                audits.append(
                    StrategyAudit(
                        name=strategy.name,
                        version=strategy.version,
                        requirements=strategy.requirements,
                        actions=result.actions,
                        issues=result.issues,
                    )
                )
                issues.extend(result.issues)
                if result.remediation_patch:
                    remediation_patches.append(result.remediation_patch)
            variants.append(
                VariantAssessment(
                    variant=variant,
                    content_sha256=sha256_text(variant_content),
                    strategies=tuple(audits),
                    issues=tuple(issues),
                )
            )
        report = QualityReport(
            assessment_key=key,
            workspace_id=context.workspace_id,
            run_id=context.run_id,
            artifact=context.artifact,
            source_bundle_hash=context.source_bundle.bundle_hash,
            variants=tuple(variants),
            policy_versions={item.name: item.version for item in strategies},
            normalization=NormalizationAudit(
                status=(
                    NormalizationStatus.FAILED
                    if normalization_error is not None
                    else NormalizationStatus.NOT_APPLICABLE
                    if not normalizers
                    else NormalizationStatus.APPLIED
                    if normalized_content is not None
                    else NormalizationStatus.UNCHANGED
                ),
                raw_sha256=sha256_text(content),
                normalized_sha256=(
                    sha256_text(normalized_content) if normalized_content is not None else None
                ),
                error=normalization_error,
            ),
        )
        return CandidateAssessment(
            raw_content=content,
            raw_media_type=media_type,
            normalized_content=normalized_content,
            normalization_patch=normalization_patch,
            remediation_patch="\n".join(dict.fromkeys(remediation_patches)) or None,
            report=report,
        )

    @staticmethod
    def _source_issues(context: QualityContext, strategies: tuple[Any, ...]) -> list[QualityIssue]:
        result: list[QualityIssue] = []
        all_source_issues = [
            *context.source_bundle.issues,
            *(issue for document in context.source_bundle.documents for issue in document.issues),
        ]
        for issue in all_source_issues:
            result.append(
                QualityIssue(
                    policy="source-ingestion",
                    version=context.source_bundle.parser_version,
                    code=issue.code,
                    message=issue.message,
                    severity=issue.severity,
                    path=issue.path,
                    details=issue.details,
                )
            )
        for strategy in strategies:
            requirements = strategy.requirements
            unavailable = context.source_bundle.completeness in {
                SourceCompleteness.EMPTY,
                SourceCompleteness.UNAVAILABLE,
            }
            incomplete = context.source_bundle.completeness != SourceCompleteness.COMPLETE
            if requirements.requires_sources and unavailable:
                result.append(
                    QualityIssue(
                        policy=strategy.name,
                        version=strategy.version,
                        code="required_source_unavailable",
                        message="该质量策略要求至少一个完整可用来源",
                    )
                )
            elif requirements.requires_complete_sources and incomplete:
                result.append(
                    QualityIssue(
                        policy=strategy.name,
                        version=strategy.version,
                        code="required_source_incomplete",
                        message="该质量策略要求完整来源集合",
                    )
                )
        return list({(item.policy, item.code, item.path): item for item in result}.values())
