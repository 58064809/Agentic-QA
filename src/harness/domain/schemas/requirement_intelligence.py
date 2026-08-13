from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from harness.domain.models import StrictModel
from harness.domain.schemas.qa_design import RiskLevel


class DeltaKind(str, Enum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"
    UNCHANGED = "UNCHANGED"
    CONFLICT = "CONFLICT"


class RequirementDeltaItem(StrictModel):
    delta_id: str = Field(pattern=r"^DELTA-\d{3,}$")
    kind: DeltaKind
    old_rule_id: str | None = None
    new_rule_id: str | None = None
    changed_fields: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    regression_impact: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sides(self) -> RequirementDeltaItem:
        if self.kind == DeltaKind.ADDED and not self.new_rule_id:
            raise ValueError("ADDED delta requires new_rule_id")
        if self.kind == DeltaKind.REMOVED and not self.old_rule_id:
            raise ValueError("REMOVED delta requires old_rule_id")
        if self.kind in {DeltaKind.MODIFIED, DeltaKind.UNCHANGED} and not (
            self.old_rule_id and self.new_rule_id
        ):
            raise ValueError("matched delta requires old and new rule IDs")
        return self


class RequirementDelta(StrictModel):
    schema_version: Literal["agentic-qa.requirement-delta.v1"] = "agentic-qa.requirement-delta.v1"
    workspace_id: str
    baseline_run_id: str
    current_run_id: str
    items: list[RequirementDeltaItem]


class SemanticContinuationMatch(StrictModel):
    old_rule_id: str
    new_rule_id: str
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=2)


class SemanticContinuationProposal(StrictModel):
    matches: list[SemanticContinuationMatch] = Field(default_factory=list, max_length=5)


class ImpactClaim(StrictModel):
    impact_id: str = Field(pattern=r"^IMPACT-\d{3,}$")
    relation: Literal["direct", "potential"]
    kind: Literal["module", "rule", "testcase", "api", "role", "state", "historical_bug"]
    target: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class ImpactAnalysis(StrictModel):
    schema_version: Literal["agentic-qa.impact-analysis.v1"] = "agentic-qa.impact-analysis.v1"
    workspace_id: str
    run_id: str
    claims: list[ImpactClaim]


class HistoricalRiskSignal(StrictModel):
    signal_id: str = Field(pattern=r"^HIST-RISK-\d{3,}$")
    category: str
    module: str | None = None
    service: str | None = None
    dependency: str | None = None
    failure_type: str | None = None
    exception_digest: str | None = None
    stable_case_identity: str | None = None
    fingerprint: str = Field(min_length=1)
    occurrence_count: int = Field(ge=1)
    evidence_refs: list[str] = Field(min_length=1)


class RiskFactors(StrictModel):
    requirement_risk: int = Field(ge=0, le=3)
    impact_radius: int = Field(ge=0, le=3)
    historical_defect: int = Field(ge=0, le=2)
    critical_business_flow: int = Field(ge=0, le=2)

    @property
    def total(self) -> int:
        return (
            self.requirement_risk
            + self.impact_radius
            + self.historical_defect
            + self.critical_business_flow
        )

    @property
    def priority(self) -> RiskLevel:
        return (
            RiskLevel.P0
            if self.total >= 8
            else RiskLevel.P1
            if self.total >= 6
            else RiskLevel.P2
            if self.total >= 3
            else RiskLevel.P3
        )


class TestDesignMethod(str, Enum):
    EQUIVALENCE = "equivalence_partitioning"
    BOUNDARY = "boundary_value"
    STATE = "state_transition"
    DECISION_TABLE = "decision_table"
    PAIRWISE = "pairwise"
    CAUSE_EFFECT = "cause_effect"
    ROLE_STATE_CONFIG = "role_state_config"
    NEGATIVE = "negative_testing"
    ERROR_GUESSING = "error_guessing"
    REGRESSION = "regression_selection"


class TestDesignDecision(StrictModel):
    rule_id: str
    methods: list[TestDesignMethod] = Field(min_length=1)
    rationale: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    required_test_types: list[str] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)


class HistoricalTestDecision(StrictModel):
    historical_case_ref: str
    similarity: float = Field(ge=0, le=1)
    decision: Literal["covered", "regression_gap", "intentionally_distinct"]
    rationale: str = Field(min_length=1)


class TestDesignPlan(StrictModel):
    schema_version: Literal["agentic-qa.test-design-plan.v1"] = "agentic-qa.test-design-plan.v1"
    requirement_catalog_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    decisions: list[TestDesignDecision]
    historical_tests: list[HistoricalTestDecision] = Field(default_factory=list)
    max_factors: int = Field(default=8, ge=1, le=8)
    max_values_per_factor: int = Field(default=12, ge=2, le=12)
    max_combinations: int = Field(default=100, ge=1, le=100)
