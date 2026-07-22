from __future__ import annotations

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


class NormalizationOperation(FrozenModel):
    kind: NormalizationOperationKind


class NormalizationProposal(FrozenModel):
    operations: tuple[NormalizationOperation, ...] = ()


class StrategyAudit(FrozenModel):
    name: str
    version: str
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


class QualityReport(FrozenModel):
    schema_version: Literal["agentic-qa.harness.quality-report.v2"] = (
        "agentic-qa.harness.quality-report.v2"
    )
    assessment_key: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    workspace_id: str
    run_id: str
    artifact: str
    source_bundle_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    variants: tuple[VariantAssessment, ...]
    policy_versions: dict[str, str]

    def verdict_for(self, variant: ArtifactVariant) -> bool:
        return next(item for item in self.variants if item.variant == variant).passed


class CandidateAssessment(FrozenModel):
    raw_content: str
    raw_media_type: str = "text/markdown"
    normalized_content: str | None = None
    normalization_patch: str | None = None
    remediation_patch: str | None = None
    report: QualityReport
