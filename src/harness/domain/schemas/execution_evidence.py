from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EXECUTION_EVIDENCE_V1_SCHEMA_VERSION = "agentic-qa.execution-evidence.v1"
EXECUTION_EVIDENCE_SCHEMA_VERSION = "agentic-qa.execution-evidence.v2"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssertionEvidence(StrictModel):
    type: str
    passed: bool
    expected: Any | None = None
    actual: Any | None = None
    path: str | None = None
    message: str = ""


class CorrelationDiagnostic(StrictModel):
    code: Literal[
        "malformed_traceparent",
        "conflicting_header_value",
        "invalid_correlation_value",
        "legacy_request_dispatch_unknown",
    ]
    header_name: str | None = None


class CorrelationObservation(StrictModel):
    field: Literal["trace_id", "span_id", "request_id", "custom_id"]
    header_name: str


class CorrelationContext(StrictModel):
    trace_id: str | None = None
    span_id: str | None = None
    trace_flags: str | None = Field(default=None, pattern=r"^[a-f0-9]{2}$")
    trace_source: Literal["traceparent", "response_header", "request_header", "runtime"] | None = (
        None
    )
    request_id: str | None = None
    custom_ids: dict[str, str] = Field(default_factory=dict)
    observations: list[CorrelationObservation] = Field(default_factory=list)
    diagnostics: list[CorrelationDiagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identifier_bounds(self) -> CorrelationContext:
        identifiers = [
            value
            for value in (self.trace_id, self.span_id, self.request_id, *self.custom_ids.values())
            if value is not None
        ]
        if any(
            not value or len(value) > 256 or "\r" in value or "\n" in value for value in identifiers
        ):
            raise ValueError("correlation identifiers must be 1-256 single-line characters")
        return self


class CaseExecutionEvidence(StrictModel):
    case_id: str
    dataset_id: str | None = None
    title: str
    method: str
    path: str
    status: Literal["passed", "failed", "error", "blocked"]
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)
    status_code: int | None = None
    assertions: list[AssertionEvidence] = Field(default_factory=list)
    error: str | None = None
    request_dispatched: bool = False
    correlation: CorrelationContext = Field(default_factory=CorrelationContext)


class ExecutionSummary(StrictModel):
    total: int = Field(ge=0)
    executed: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    errors: int = Field(ge=0)
    blocked: int = Field(ge=0)


class ExecutionEnvironment(StrictModel):
    name: str
    base_url_env: str
    base_url_configured: bool
    allowed_methods: list[str] = Field(min_length=1)
    request_timeout_seconds: int = Field(ge=1, le=60)


class ExecutionEvidence(StrictModel):
    schema_version: Literal["agentic-qa.execution-evidence.v2"]
    run_id: str
    source_cases_path: str
    source_cases_schema_version: str
    started_at: datetime
    completed_at: datetime
    environment: ExecutionEnvironment
    summary: ExecutionSummary
    cases: list[CaseExecutionEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_summary(self) -> ExecutionEvidence:
        _validate_execution_summary(self)
        return self


class CaseExecutionEvidenceV1(StrictModel):
    case_id: str
    title: str
    method: str
    path: str
    status: Literal["passed", "failed", "error", "blocked"]
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=0)
    status_code: int | None = None
    assertions: list[AssertionEvidence] = Field(default_factory=list)
    error: str | None = None


class ExecutionEvidenceV1(StrictModel):
    schema_version: Literal["agentic-qa.execution-evidence.v1"]
    run_id: str
    source_cases_path: str
    source_cases_schema_version: str
    started_at: datetime
    completed_at: datetime
    environment: ExecutionEnvironment
    summary: ExecutionSummary
    cases: list[CaseExecutionEvidenceV1] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_summary(self) -> ExecutionEvidenceV1:
        _validate_execution_summary(self)
        return self


def _validate_execution_summary(evidence: ExecutionEvidence | ExecutionEvidenceV1) -> None:
    counts = {
        status: sum(case.status == status for case in evidence.cases)
        for status in ("passed", "failed", "error", "blocked")
    }
    expected = {
        "total": len(evidence.cases),
        "executed": counts["passed"] + counts["failed"] + counts["error"],
        "passed": counts["passed"],
        "failed": counts["failed"],
        "errors": counts["error"],
        "blocked": counts["blocked"],
    }
    if evidence.summary.model_dump() != expected:
        raise ValueError(f"execution summary does not match cases: {expected}")
    if evidence.completed_at < evidence.started_at:
        raise ValueError("completed_at cannot be earlier than started_at")


def load_execution_evidence(value: Any) -> ExecutionEvidence:
    """Validate v2 or project immutable v1 evidence into the current read model."""
    if isinstance(value, str | bytes | bytearray):
        decoded = json.loads(value)
        if decoded.get("schema_version") == EXECUTION_EVIDENCE_SCHEMA_VERSION:
            return ExecutionEvidence.model_validate(decoded)
        legacy = ExecutionEvidenceV1.model_validate(decoded)
        payload = legacy.model_dump(mode="python")
    elif (
        isinstance(value, dict) and value.get("schema_version") == EXECUTION_EVIDENCE_SCHEMA_VERSION
    ):
        return ExecutionEvidence.model_validate(value)
    else:
        legacy = ExecutionEvidenceV1.model_validate(value)
        payload = legacy.model_dump(mode="python")
    payload["schema_version"] = EXECUTION_EVIDENCE_SCHEMA_VERSION
    payload["cases"] = [
        {
            **case,
            "dataset_id": _legacy_dataset_id(case["case_id"]),
            "request_dispatched": case["status"] in {"passed", "failed"},
            "correlation": {
                "diagnostics": (
                    [{"code": "legacy_request_dispatch_unknown"}]
                    if case["status"] == "error"
                    else []
                )
            },
        }
        for case in payload["cases"]
    ]
    return ExecutionEvidence.model_validate(payload)


def _legacy_dataset_id(case_id: str) -> str | None:
    parts = case_id.split("::")
    if len(parts) < 2 or parts[1] == "cleanup":
        return None
    return parts[1]
