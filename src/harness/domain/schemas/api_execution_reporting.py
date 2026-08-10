from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from harness.domain.models import StrictModel, normalize_workspace_id


class ApiExecutionEvent(StrictModel):
    schema_version: Literal["agentic-qa.api-execution-events.v1"] = (
        "agentic-qa.api-execution-events.v1"
    )
    sequence: int = Field(ge=1)
    timestamp: datetime
    execution_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=80)
    phase: str = Field(min_length=1, max_length=40)
    outcome: Literal["started", "passed", "failed", "broken", "skipped", "pending"]
    case_id: str | None = None
    dataset_id: str | None = None
    cleanup_id: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    status_code: int | None = Field(default=None, ge=100, le=599)
    details: dict[str, Any] = Field(default_factory=dict)
    previous_event_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    event_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ApiReportCounts(StrictModel):
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    broken: int = Field(ge=0)
    skipped: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> ApiReportCounts:
        if self.total != self.passed + self.failed + self.broken + self.skipped:
            raise ValueError("report count total does not match statuses")
        return self


class ApiReportCase(StrictModel):
    case_id: str
    title: str
    status: Literal["passed", "failed", "broken", "skipped"]
    reason_code: str
    evidence_status: Literal["passed", "failed", "error", "blocked"] | None = None


class ApiReportSummary(StrictModel):
    schema_version: Literal["agentic-qa.api-report-summary.v1"] = "agentic-qa.api-report-summary.v1"
    execution_id: str
    environment: str
    result: Literal["passed", "failed"]
    counts: ApiReportCounts
    cases: list[ApiReportCase]


class CleanupJournalCounts(StrictModel):
    total: int = Field(ge=0)
    pending: int = Field(ge=0)
    running: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> CleanupJournalCounts:
        if self.total != self.pending + self.running + self.completed + self.failed:
            raise ValueError("cleanup count total does not match states")
        return self


class CleanupJournalSummary(StrictModel):
    schema_version: Literal["agentic-qa.cleanup-journal-summary.v1"] = (
        "agentic-qa.cleanup-journal-summary.v1"
    )
    execution_id: str
    status: Literal["not_required", "complete", "pending", "indeterminate", "failed"]
    counts: CleanupJournalCounts
    obligation_ids: list[str] = Field(default_factory=list)


class GenerateApiAllureReportCommand(StrictModel):
    schema_version: Literal["agentic-qa.harness.generate-api-allure-report-command.v1"] = (
        "agentic-qa.harness.generate-api-allure-report-command.v1"
    )
    workspace_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def normalize_workspace(self) -> GenerateApiAllureReportCommand:
        self.workspace_id = normalize_workspace_id(self.workspace_id)
        return self


class GenerateApiAllureReportResult(StrictModel):
    schema_version: Literal["agentic-qa.harness.generate-api-allure-report-result.v1"] = (
        "agentic-qa.harness.generate-api-allure-report-result.v1"
    )
    workspace_id: str
    execution_id: str
    status: Literal["generated", "results_only"]
    allure_results_path: str
    allure_report_path: str | None = None
    message: str = ""


class ResumeApiCleanupCommand(StrictModel):
    schema_version: Literal["agentic-qa.harness.resume-api-cleanup-command.v1"] = (
        "agentic-qa.harness.resume-api-cleanup-command.v1"
    )
    workspace_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1, max_length=128)
    environment: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def normalize_workspace(self) -> ResumeApiCleanupCommand:
        self.workspace_id = normalize_workspace_id(self.workspace_id)
        return self


class ResumeApiCleanupResult(StrictModel):
    schema_version: Literal["agentic-qa.harness.resume-api-cleanup-result.v1"] = (
        "agentic-qa.harness.resume-api-cleanup-result.v1"
    )
    workspace_id: str
    execution_id: str
    recovery_id: str
    status: Literal["complete", "failed", "indeterminate"]
    cleanup_summary_path: str
    summary: CleanupJournalSummary
