from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harness.domain.security import contains_likely_secret

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
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
INVALID_WORKSPACE_CHARS = frozenset('<>:"/\\|?*')


def normalize_workspace_id(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    if normalized == "prd" or normalized.startswith("prd/") or "/prd/" in f"/{normalized}/":
        raise ValueError("旧工作区不受 Harness 支持；请使用 workspaces/<id>")
    if normalized.startswith("workspaces/"):
        normalized = normalized.removeprefix("workspaces/")
    if (
        not normalized
        or "/" in normalized
        or normalized in {".", ".."}
        or len(normalized) > 128
        or normalized.endswith(".")
        or any(character in INVALID_WORKSPACE_CHARS for character in normalized)
        or any(ord(character) < 32 for character in normalized)
        or normalized.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES
    ):
        raise ValueError("workspace 必须是单个安全目录名")
    return normalized


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionProfile(StrictModel):
    schema_version: Literal["agentic-qa.harness.execution-profile.v2"] = (
        "agentic-qa.harness.execution-profile.v2"
    )
    environment: str = Field(default="analysis-only", min_length=1)
    base_url_env: str | None = Field(default=None, pattern=r"^[A-Z_][A-Z0-9_]*$")
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

    @model_validator(mode="after")
    def validate_environment_safety(self) -> ExecutionProfile:
        segments = set(re.split(r"[^a-z0-9]+", self.environment.strip().lower()))
        if segments & {"prod", "production", "live"}:
            raise ValueError("production-like environments are not supported")
        if self.environment == "analysis-only" and self.allow_ui_mutations:
            raise ValueError("analysis-only cannot allow UI mutations")
        return self


class ExecutionEnvironmentPolicy(StrictModel):
    base_url_env: str | None = Field(default=None, pattern=r"^[A-Z_][A-Z0-9_]*$")
    allowed_http_methods: list[str] = Field(default_factory=lambda: ["GET", "HEAD", "OPTIONS"])
    allow_ui_mutations: bool = False
    max_request_timeout_seconds: int = Field(default=10, ge=1, le=60)

    @field_validator("allowed_http_methods")
    @classmethod
    def normalize_methods(cls, value: list[str]) -> list[str]:
        methods = list(dict.fromkeys(item.strip().upper() for item in value if item.strip()))
        if not methods:
            raise ValueError("allowed_http_methods cannot be empty")
        return methods


class StartRunCommand(StrictModel):
    schema_version: Literal["agentic-qa.harness.start-run-command.v2"] = (
        "agentic-qa.harness.start-run-command.v2"
    )
    workspace_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    expected_artifacts: list[str] = Field(default_factory=lambda: ["testcases"])
    execution_profile: ExecutionProfile = Field(default_factory=ExecutionProfile)

    @field_validator("workspace_id")
    @classmethod
    def reject_legacy_workspace(cls, value: str) -> str:
        return normalize_workspace_id(value)

    @field_validator("goal")
    @classmethod
    def reject_secrets_in_goal(cls, value: str) -> str:
        if contains_likely_secret(value):
            raise ValueError("goal contains a likely secret; use environment variables instead")
        return value

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
    schema_version: Literal["agentic-qa.harness.qa-plan.v2"] = "agentic-qa.harness.qa-plan.v2"
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
    schema_version: Literal["agentic-qa.harness.agent-manifest.v2"] = (
        "agentic-qa.harness.agent-manifest.v2"
    )
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    role: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    tool_allowlist: list[str] = Field(default_factory=list)
    input_schema: str = "agentic-qa.harness.agent-input.v2"
    output_schema: str = "agentic-qa.harness.agent-output.v2"
    max_steps: int = Field(default=8, ge=1, le=50)


class SkillManifest(StrictModel):
    schema_version: Literal["agentic-qa.harness.skill-manifest.v2"] = (
        "agentic-qa.harness.skill-manifest.v2"
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
    schema_version: Literal["agentic-qa.harness.tool-manifest.v2"] = (
        "agentic-qa.harness.tool-manifest.v2"
    )
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    provider: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    risk: ToolRisk
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    idempotency: Literal["read", "keyed", "none"]


class ArtifactVariant(str, Enum):
    RAW = "raw"
    NORMALIZED = "normalized"


class ArtifactVersion(StrictModel):
    variant: ArtifactVariant
    path: str
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ArtifactVersionRef(StrictModel):
    artifact: str
    variant: ArtifactVariant
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    assessment_key: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    quality_report_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ApprovedArtifactVersion(ArtifactVersionRef):
    path: str


class ArtifactCandidate(StrictModel):
    artifact: str
    path: str
    media_type: str | None = "text/markdown"
    status: Literal["needs_human_review", "partial", "provenance_incomplete"] = "needs_human_review"
    partial: bool | None = False
    evidence: list[str] | None = Field(default_factory=list)
    provenance_complete: bool = True
    versions: list[ArtifactVersion] = Field(default_factory=list)
    assessment_key: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    quality_report_path: str | None = None
    quality_report_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    source_bundle_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    policy_versions: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_quality_flag(cls, value: Any) -> Any:
        if isinstance(value, dict) and "quality_passed" in value:
            value = dict(value)
            value.pop("quality_passed", None)
        return value

    def version_ref(self, variant: ArtifactVariant) -> ArtifactVersionRef:
        version = next((item for item in self.versions if item.variant == variant), None)
        if version is None or self.assessment_key is None or self.quality_report_sha256 is None:
            raise ValueError(f"candidate version 或质量 provenance 不可用: {variant.value}")
        return ArtifactVersionRef(
            artifact=self.artifact,
            variant=variant,
            content_sha256=version.content_sha256,
            assessment_key=self.assessment_key,
            quality_report_sha256=self.quality_report_sha256,
        )


class BudgetUsage(StrictModel):
    model_calls: int = 0
    tool_calls: int = 0
    replans: int = 0
    elapsed_seconds: float = 0


class HarnessEvent(StrictModel):
    schema_version: Literal["agentic-qa.harness.event.v2"] = "agentic-qa.harness.event.v2"
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
    "on_hold",
]


class RunSnapshot(StrictModel):
    schema_version: Literal["agentic-qa.harness.run-snapshot.v2"] = (
        "agentic-qa.harness.run-snapshot.v2"
    )
    run_id: str
    workspace_id: str
    status: RunStatus
    request: StartRunCommand
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


class ArtifactDiffEndpoint(str, Enum):
    PUBLISHED = "published"
    RAW = "raw"
    NORMALIZED = "normalized"


class ArtifactDiffResult(StrictModel):
    artifact: str
    before: ArtifactDiffEndpoint
    after: ArtifactDiffEndpoint
    before_sha256: str
    after_sha256: str
    diff: str
    truncated: bool = False


class ReviewDecision(StrictModel):
    schema_version: Literal["agentic-qa.harness.review-decision.v2"] = (
        "agentic-qa.harness.review-decision.v2"
    )
    intent: ReviewIntent
    target_artifact: str | None = None
    reason: str = Field(min_length=1)
    revision_request: str | None = None
    reviewed_by: str = Field(min_length=1)
    versions: list[ArtifactVersionRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_revision(self) -> ReviewDecision:
        if self.intent == ReviewIntent.REVISE and not self.revision_request:
            raise ValueError("revise requires revision_request")
        if self.intent != ReviewIntent.APPROVE and self.versions:
            raise ValueError("versions are only allowed for approve decisions")
        if len({item.artifact for item in self.versions}) != len(self.versions):
            raise ValueError("approve versions must contain each artifact at most once")
        return self


class CreateWorkspaceCommand(StrictModel):
    schema_version: Literal["agentic-qa.harness.create-workspace-command.v2"] = (
        "agentic-qa.harness.create-workspace-command.v2"
    )
    workspace_id: str = Field(min_length=1)
    quality_policies: list[str] = Field(default_factory=list)

    @field_validator("workspace_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return normalize_workspace_id(value)

    @field_validator("quality_policies")
    @classmethod
    def unique_policies(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("quality_policies cannot contain duplicates")
        return value


class RunRef(StrictModel):
    schema_version: Literal["agentic-qa.harness.run-ref.v2"] = "agentic-qa.harness.run-ref.v2"
    workspace_id: str = Field(min_length=1)
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

    @field_validator("workspace_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return normalize_workspace_id(value)


class GetArtifactDiffQuery(RunRef):
    schema_version: Literal["agentic-qa.harness.get-artifact-diff-query.v2"] = (
        "agentic-qa.harness.get-artifact-diff-query.v2"
    )
    artifact: str
    before: ArtifactDiffEndpoint
    after: ArtifactDiffEndpoint


class ResumeRunCommand(RunRef):
    schema_version: Literal["agentic-qa.harness.resume-run-command.v2"] = (
        "agentic-qa.harness.resume-run-command.v2"
    )


class ReviewRunCommand(RunRef):
    schema_version: Literal["agentic-qa.harness.review-run-command.v2"] = (
        "agentic-qa.harness.review-run-command.v2"
    )
    decision: ReviewDecision
