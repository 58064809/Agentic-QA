from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_PREFIX = "agentic-qa.harness"
UTC = timezone.utc
ARTIFACT_TYPES = (
    "requirement_analysis",
    "testcases",
    "api_test_draft",
    "ui_test_draft",
    "api_discovery_report",
    "qa_report",
    "execution_report",
    "failure_analysis",
    "bug_draft",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionProfile(StrictModel):
    schema_version: Literal["agentic-qa.harness.execution-profile.v1"] = (
        "agentic-qa.harness.execution-profile.v1"
    )
    environment: str = "analysis-only"
    base_url_env: str | None = None
    allowed_http_methods: list[str] = Field(default_factory=lambda: ["GET", "HEAD", "OPTIONS"])
    allow_ui_mutations: bool = False
    request_timeout_seconds: int = Field(default=10, ge=1, le=60)

    @field_validator("allowed_http_methods")
    @classmethod
    def normalize_methods(cls, value: list[str]) -> list[str]:
        methods = list(dict.fromkeys(item.strip().upper() for item in value if item.strip()))
        if not methods:
            raise ValueError("allowed_http_methods cannot be empty")
        return methods


class TaskRequest(StrictModel):
    schema_version: Literal["agentic-qa.harness.task-request.v1"] = (
        "agentic-qa.harness.task-request.v1"
    )
    workspace: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    expected_artifacts: list[str] = Field(default_factory=lambda: ["testcases"])
    execution_profile: ExecutionProfile = Field(default_factory=ExecutionProfile)

    @field_validator("workspace")
    @classmethod
    def reject_legacy_workspace(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/").strip("/")
        if normalized == "prd" or normalized.startswith("prd/") or "/prd/" in f"/{normalized}/":
            raise ValueError("旧工作区不受 Harness 支持；请使用 workspaces/<id>")
        if normalized.startswith("workspaces/"):
            normalized = normalized.removeprefix("workspaces/")
        if not normalized or "/" in normalized or normalized in {".", ".."}:
            raise ValueError("workspace 必须是单个安全标识")
        return normalized

    @field_validator("expected_artifacts")
    @classmethod
    def validate_artifacts(cls, value: list[str]) -> list[str]:
        artifacts = list(dict.fromkeys(value))
        unknown = sorted(set(artifacts) - set(ARTIFACT_TYPES))
        if unknown:
            raise ValueError(f"未知产物类型: {', '.join(unknown)}")
        if not artifacts:
            raise ValueError("expected_artifacts cannot be empty")
        return artifacts


class EvidenceRequirement(StrictModel):
    kind: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required: bool = True


class PlanTask(StrictModel):
    id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)


class QAPlan(StrictModel):
    schema_version: Literal["agentic-qa.harness.qa-plan.v1"] = "agentic-qa.harness.qa-plan.v1"
    tasks: list[PlanTask] = Field(min_length=1)
    revision: int = Field(default=0, ge=0)
    rationale: str = ""

    @model_validator(mode="after")
    def validate_graph(self) -> QAPlan:
        ids = [task.id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("plan task ids must be unique")
        known = set(ids)
        for task in self.tasks:
            missing = set(task.dependencies) - known
            if missing:
                raise ValueError(f"task {task.id} has unknown dependencies: {sorted(missing)}")
            if task.id in task.dependencies:
                raise ValueError(f"task {task.id} cannot depend on itself")
        pending = {task.id: set(task.dependencies) for task in self.tasks}
        while pending:
            ready = {task_id for task_id, deps in pending.items() if not deps}
            if not ready:
                raise ValueError("plan contains a dependency cycle")
            pending = {
                task_id: deps - ready for task_id, deps in pending.items() if task_id not in ready
            }
        return self


class AgentManifest(StrictModel):
    schema_version: Literal["agentic-qa.harness.agent-manifest.v1"] = (
        "agentic-qa.harness.agent-manifest.v1"
    )
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    role: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    tool_allowlist: list[str] = Field(default_factory=list)
    input_schema: str = "agentic-qa.harness.agent-input.v1"
    output_schema: str = "agentic-qa.harness.agent-output.v1"
    max_steps: int = Field(default=8, ge=1, le=50)


class SkillManifest(StrictModel):
    schema_version: Literal["agentic-qa.harness.skill-manifest.v1"] = (
        "agentic-qa.harness.skill-manifest.v1"
    )
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    description: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    references: list[str] = Field(default_factory=list)


class ToolRisk(str, Enum):
    READ_ONLY = "read_only"
    TEST_MUTATION = "test_mutation"
    ARTIFACT_WRITE = "artifact_write"
    PUBLISH = "publish"


class ToolManifest(StrictModel):
    schema_version: Literal["agentic-qa.harness.tool-manifest.v1"] = (
        "agentic-qa.harness.tool-manifest.v1"
    )
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    provider: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    risk: ToolRisk
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    idempotency: Literal["read", "keyed", "none"]


class ArtifactCandidate(StrictModel):
    artifact: str
    path: str
    media_type: str = "text/markdown"
    status: Literal["needs_human_review", "partial"] = "needs_human_review"
    quality_passed: bool = True
    evidence: list[str] = Field(default_factory=list)


class BudgetUsage(StrictModel):
    model_calls: int = 0
    tool_calls: int = 0
    replans: int = 0
    elapsed_seconds: float = 0


class HarnessEvent(StrictModel):
    schema_version: Literal["agentic-qa.harness.event.v1"] = "agentic-qa.harness.event.v1"
    sequence: int = Field(ge=1)
    run_id: str
    type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    task_id: str | None = None
    agent: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


RunStatus = Literal[
    "planning",
    "running",
    "needs_human_review",
    "partial",
    "rejected",
    "needs_revision",
    "published",
    "failed",
    "recoverable",
]


class RunSnapshot(StrictModel):
    schema_version: Literal["agentic-qa.harness.run-snapshot.v1"] = (
        "agentic-qa.harness.run-snapshot.v1"
    )
    run_id: str
    workspace: str
    status: RunStatus
    request: TaskRequest
    plan: QAPlan | None = None
    completed_tasks: list[str] = Field(default_factory=list)
    pending_tasks: list[str] = Field(default_factory=list)
    candidates: list[ArtifactCandidate] = Field(default_factory=list)
    review_status: dict[str, str] = Field(default_factory=dict)
    delegations: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    model_usage: dict[str, int] = Field(default_factory=dict)
    model_routes: list[dict[str, Any]] = Field(default_factory=list)
    interrupt: dict[str, Any] | None = None
    budget: BudgetUsage = Field(default_factory=BudgetUsage)
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class ReviewIntent(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REVISE = "revise"
    HOLD = "hold"
    SHOW_DIFF = "show_diff"


class ReviewDecision(StrictModel):
    schema_version: Literal["agentic-qa.harness.review-decision.v1"] = (
        "agentic-qa.harness.review-decision.v1"
    )
    intent: ReviewIntent
    target_artifact: str | None = None
    reason: str = Field(min_length=1)
    revision_request: str | None = None
    reviewed_by: str = "human"

    @model_validator(mode="after")
    def validate_revision(self) -> ReviewDecision:
        if self.intent == ReviewIntent.REVISE and not self.revision_request:
            raise ValueError("revise requires revision_request")
        return self
