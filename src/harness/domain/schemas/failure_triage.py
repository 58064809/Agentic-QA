from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FAILURE_TRIAGE_SCHEMA_VERSION = "agentic-qa.failure-triage.v1"
FAILURE_TRIAGE_V2_SCHEMA_VERSION = "agentic-qa.failure-triage.v2"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FailureObservation(StrictModel):
    case_id: str
    title: str
    method: str
    path: str
    evidence_status: Literal["failed", "error", "blocked"]
    category: Literal["assertion_mismatch", "execution_error", "execution_policy_blocked"]
    root_cause_status: Literal["unconfirmed"]
    evidence_ref: str
    observation: str
    bug_candidate_id: str | None = None


class BugCandidate(StrictModel):
    id: str
    case_id: str
    title: str
    status: Literal["needs_human_review"]
    evidence_ref: str
    request: str
    expected: list[str] = Field(min_length=1)
    actual: list[str] = Field(min_length=1)
    pending: list[str] = Field(min_length=1)


class FailureTriageSummary(StrictModel):
    total_non_passed: int = Field(ge=1)
    assertion_failures: int = Field(ge=0)
    execution_errors: int = Field(ge=0)
    policy_blocked: int = Field(ge=0)
    bug_candidates: int = Field(ge=0)


class FailureTriage(StrictModel):
    schema_version: Literal["agentic-qa.failure-triage.v1"]
    source_evidence_path: str
    source_evidence_schema: Literal["agentic-qa.execution-evidence.v1"]
    source_run_id: str
    summary: FailureTriageSummary
    observations: list[FailureObservation] = Field(min_length=1)
    bug_candidates: list[BugCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts_and_links(self) -> FailureTriage:
        expected = {
            "total_non_passed": len(self.observations),
            "assertion_failures": sum(
                item.category == "assertion_mismatch" for item in self.observations
            ),
            "execution_errors": sum(
                item.category == "execution_error" for item in self.observations
            ),
            "policy_blocked": sum(
                item.category == "execution_policy_blocked" for item in self.observations
            ),
            "bug_candidates": len(self.bug_candidates),
        }
        if self.summary.model_dump() != expected:
            raise ValueError(f"failure triage summary does not match observations: {expected}")
        candidate_ids = {candidate.id for candidate in self.bug_candidates}
        links = {item.bug_candidate_id for item in self.observations if item.bug_candidate_id}
        if links != candidate_ids:
            raise ValueError("failure observation and bug candidate links do not match")
        if any(
            item.evidence_status != "failed" and item.bug_candidate_id for item in self.observations
        ):
            raise ValueError("error or blocked evidence cannot create bug candidates")
        return self


FailureCategory = Literal[
    "application",
    "dependency",
    "database",
    "timeout",
    "network",
    "auth",
    "data",
    "contract",
    "environment",
    "rate-limit",
    "resource",
    "test-script",
    "test-data",
    "unknown",
]


class FailureHypothesis(StrictModel):
    category: FailureCategory
    service: str | None = None
    exception_type: str | None = None
    summary: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list)


class FailureTriageProposal(StrictModel):
    primary: FailureHypothesis
    alternatives: list[FailureHypothesis] = Field(default_factory=list, max_length=3)
    recommended_actions: list[str] = Field(default_factory=list, max_length=10)


class FailureTriageV2(StrictModel):
    schema_version: Literal["agentic-qa.failure-triage.v2"] = "agentic-qa.failure-triage.v2"
    collection_id: str
    execution_id: str
    case_id: str
    dataset_id: str | None = None
    execution_evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    log_evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    log_analysis_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    triage_status: Literal["success", "insufficient_evidence", "failed"]
    likelihood: Literal["highly_likely", "probable", "insufficient_evidence"]
    primary: FailureHypothesis | None = None
    alternatives: list[FailureHypothesis] = Field(default_factory=list, max_length=3)
    recommended_actions: list[str] = Field(default_factory=list, max_length=10)
    available_evidence_refs: list[str]
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_semantics(self) -> FailureTriageV2:
        allowed = set(self.available_evidence_refs)
        hypotheses = [item for item in [self.primary, *self.alternatives] if item]
        if any(not set(item.evidence_refs) <= allowed for item in hypotheses):
            raise ValueError("failure triage contains unresolved evidence references")
        if self.triage_status != "failed" and self.primary is None:
            raise ValueError("completed failure triage requires a primary hypothesis")
        if self.primary:
            expected = (
                "highly_likely"
                if self.primary.confidence >= 0.9 and self.primary.evidence_refs
                else "probable"
                if self.primary.confidence >= 0.7 and self.primary.evidence_refs
                else "insufficient_evidence"
            )
            if self.likelihood != expected:
                raise ValueError("triage likelihood does not match confidence and citations")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.content_sha256 != expected_hash:
            raise ValueError("failure triage content hash does not match")
        return self
