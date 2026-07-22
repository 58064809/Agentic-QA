from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from harness.application.source import SourceBundle, SourceIssueSeverity
from harness.domain.models import ArtifactVariant


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StrategyRequirements(FrozenModel):
    requires_sources: bool = False
    requires_complete_sources: bool = False


class QualityComponentConfiguration(FrozenModel):
    """Validated non-secret configuration included in an assessment identity."""


class QualityContext(FrozenModel):
    workspace_id: str
    run_id: str
    artifact: str
    source_bundle: SourceBundle


class QualityIssue(FrozenModel):
    policy: str
    version: str
    code: str
    message: str
    severity: SourceIssueSeverity = SourceIssueSeverity.BLOCKER
    path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class StrategyResult(FrozenModel):
    issues: tuple[QualityIssue, ...] = ()
    actions: tuple[str, ...] = ()
    remediation_patch: str | None = None


class NormalizationOperationKind(str, Enum):
    NORMALIZE_LINE_ENDINGS = "normalize_line_endings"
    TRIM_TRAILING_WHITESPACE = "trim_trailing_whitespace"
    ENSURE_FINAL_NEWLINE = "ensure_final_newline"
    NORMALIZE_MARKDOWN_TABLE_DELIMITER_SPACING = "normalize_markdown_table_delimiter_spacing"


class NormalizationStatus(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    UNCHANGED = "unchanged"
    APPLIED = "applied"
    FAILED = "failed"


class NormalizationOperation(FrozenModel):
    kind: NormalizationOperationKind


class NormalizationProposal(FrozenModel):
    operations: tuple[NormalizationOperation, ...] = ()


class StrategyAudit(FrozenModel):
    name: str
    version: str
    configuration_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    requirements: StrategyRequirements
    actions: tuple[str, ...] = ()
    issues: tuple[QualityIssue, ...] = ()


class VariantAssessment(FrozenModel):
    variant: ArtifactVariant
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    strategies: tuple[StrategyAudit, ...] = ()
    issues: tuple[QualityIssue, ...] = ()

    @property
    def passed(self) -> bool:
        return not any(issue.severity == SourceIssueSeverity.BLOCKER for issue in self.issues)


class NormalizationAudit(FrozenModel):
    status: NormalizationStatus
    components: tuple[NormalizationComponentAudit, ...] = ()
    raw_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    normalized_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    error: str | None = None


class NormalizationComponentAudit(FrozenModel):
    name: str
    version: str
    configuration_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    operations: tuple[NormalizationOperationKind, ...] = ()
    status: NormalizationStatus
    error: str | None = None


class QualityReport(FrozenModel):
    schema_version: Literal["agentic-qa.harness.quality-report.v2"] = (
        "agentic-qa.harness.quality-report.v2"
    )
    assessment_key: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    assessment_pipeline_version: str
    raw_media_type: str
    workspace_id: str
    run_id: str
    artifact: str
    source_bundle_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    variants: tuple[VariantAssessment, ...]
    policy_versions: dict[str, str]
    normalization: NormalizationAudit

    def verdict_for(self, variant: ArtifactVariant) -> bool:
        matches = [item for item in self.variants if item.variant == variant]
        if len(matches) != 1:
            raise ValueError(f"quality report 缺少或重复 variant: {variant.value}")
        return matches[0].passed

    def recompute_assessment_key(self) -> str:
        raw = next(item for item in self.variants if item.variant == ArtifactVariant.RAW)
        payload = {
            "schema": "agentic-qa.harness.assessment-input.v2",
            "pipeline_version": self.assessment_pipeline_version,
            "workspace_id": self.workspace_id,
            "run_id": self.run_id,
            "artifact": self.artifact,
            "raw": {"media_type": self.raw_media_type, "sha256": raw.content_sha256},
            "source_bundle_hash": self.source_bundle_hash,
            "normalizers": [
                {
                    "name": item.name,
                    "version": item.version,
                    "configuration_sha256": item.configuration_sha256,
                }
                for item in self.normalization.components
            ],
            "strategies": [
                {
                    "name": item.name,
                    "version": item.version,
                    "configuration_sha256": item.configuration_sha256,
                    "requirements": item.requirements.model_dump(mode="json"),
                }
                for item in raw.strategies
            ],
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class CandidateAssessment(FrozenModel):
    raw_content: str
    raw_media_type: str = "text/markdown"
    normalized_content: str | None = None
    normalization_patch: str | None = None
    remediation_patch: str | None = None
    report: QualityReport
