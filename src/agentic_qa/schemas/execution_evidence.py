from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EXECUTION_EVIDENCE_SCHEMA_VERSION = "agentic-qa.execution-evidence.v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionProfile(StrictModel):
    schema_version: Literal["agentic-qa.execution-profile.v1"] = "agentic-qa.execution-profile.v1"
    environment_name: str = Field(default="local", min_length=1)
    base_url_env: str = Field(default="AGENTIC_QA_BASE_URL", pattern=r"^[A-Z_][A-Z0-9_]*$")
    allowed_methods: list[str] = Field(default_factory=lambda: ["GET", "HEAD", "OPTIONS"])
    request_timeout_seconds: int = Field(default=10, ge=1, le=60)


class AssertionEvidence(StrictModel):
    type: str
    passed: bool
    expected: Any | None = None
    actual: Any | None = None
    path: str | None = None
    message: str = ""


class CaseExecutionEvidence(StrictModel):
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
    schema_version: Literal["agentic-qa.execution-evidence.v1"]
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
        counts = {
            status: sum(case.status == status for case in self.cases)
            for status in ("passed", "failed", "error", "blocked")
        }
        expected = {
            "total": len(self.cases),
            "executed": counts["passed"] + counts["failed"] + counts["error"],
            "passed": counts["passed"],
            "failed": counts["failed"],
            "errors": counts["error"],
            "blocked": counts["blocked"],
        }
        if self.summary.model_dump() != expected:
            raise ValueError(f"execution summary does not match cases: {expected}")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be earlier than started_at")
        return self
