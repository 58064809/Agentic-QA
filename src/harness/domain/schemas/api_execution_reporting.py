from __future__ import annotations

import hashlib
import json
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


class ApiExecutionPlanCleanup(StrictModel):
    cleanup_id: str
    method: str
    path_template: str
    request_structure_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation_classification: Literal[
        "read_only", "mutation_cleanup", "mutation_idempotent", "mutation_manual"
    ]
    idempotency_header: str | None = None
    idempotency_key_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ApiExecutionPlanCase(StrictModel):
    case_id: str = Field(min_length=1)
    source_case_id: str = Field(min_length=1)
    dataset_id: str | None = None
    method: str | None = None
    path_template: str | None = None
    contract_status: Literal["missing", "pending_confirmation", "partial", "confirmed"]
    request_structure_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cleanup_ids: list[str] = Field(default_factory=list)
    cleanups: list[ApiExecutionPlanCleanup] = Field(default_factory=list)
    operation_classification: Literal[
        "read_only", "mutation_cleanup", "mutation_idempotent", "mutation_manual"
    ]
    idempotency_header: str | None = None
    idempotency_key_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class _ApiExecutionPlanBase(StrictModel):
    workspace_id: str
    execution_id: str
    service: str
    environment: str
    created_at: datetime
    source_cases_path: str
    source_cases_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    structural_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    execution_profile_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    authentication_mode: Literal["none", "login", "static_token"]
    isolation_mode: Literal["shared", "namespace"]
    namespace_location: Literal["header", "query", "body"] | None = None
    namespace_name: str | None = None
    namespace_value_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    cases: list[ApiExecutionPlanCase] = Field(min_length=1)
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_semantic_hash(self) -> _ApiExecutionPlanBase:
        payload = self.model_dump(mode="json", exclude={"plan_sha256"})
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected = hashlib.sha256(encoded).hexdigest()
        if self.plan_sha256 != expected:
            raise ValueError("execution plan semantic hash does not match its content")
        return self


class ApiExecutionPlanV1(_ApiExecutionPlanBase):
    schema_version: Literal["agentic-qa.api-execution-plan.v1"] = "agentic-qa.api-execution-plan.v1"


class ApiExecutionPlan(_ApiExecutionPlanBase):
    schema_version: Literal["agentic-qa.api-execution-plan.v2"] = "agentic-qa.api-execution-plan.v2"
    source_publication_id: str = Field(min_length=1)
    source_history_path: str = Field(min_length=1)
    policy_sha256: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


def parse_api_execution_plan_json(value: str) -> ApiExecutionPlan | ApiExecutionPlanV1:
    payload = json.loads(value)
    if payload.get("schema_version") == "agentic-qa.api-execution-plan.v1":
        return ApiExecutionPlanV1.model_validate(payload)
    return ApiExecutionPlan.model_validate(payload)


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
    armed: int = Field(default=0, ge=0)
    pending: int = Field(ge=0)
    running: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> CleanupJournalCounts:
        if self.total != self.armed + self.pending + self.running + self.completed + self.failed:
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
    status: Literal["complete", "failed", "indeterminate", "manual_reapproval_required"]
    cleanup_summary_path: str
    summary: CleanupJournalSummary
    original_policy_sha256: str | None = None
    current_policy_sha256: str | None = None
    reason: str | None = None
