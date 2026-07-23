from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, field_validator

from harness.domain.models import (
    ARTIFACT_TYPES,
    ArtifactVariant,
    StrictModel,
    normalize_workspace_id,
)
from harness.domain.security import contains_likely_secret

SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class AgentRequest(StrictModel):
    """High-level, review-safe request for generating QA candidates from local sources."""

    schema_version: Literal["agentic-qa.harness.agent-request.v1"] = (
        "agentic-qa.harness.agent-request.v1"
    )
    request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        description="Optional caller identity; changing it intentionally creates a new request.",
    )
    workspace_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Optional managed workspace ID; omit to derive a deterministic safe ID.",
    )
    goal: str = Field(
        min_length=1,
        description="QA analysis goal. Generated output remains an unapproved candidate.",
    )
    source_paths: list[str] = Field(
        min_length=1,
        max_length=16,
        description=(
            "Absolute UTF-8 text file or directory paths under server allow-source-root values."
        ),
    )
    expected_artifacts: list[str] = Field(
        default_factory=lambda: ["testcases"],
        description="Artifact types to generate; defaults to testcases.",
    )
    quality_policies: list[str] = Field(
        default_factory=list,
        description="Registered quality policy names; arbitrary Python imports are forbidden.",
    )

    @field_validator("workspace_id")
    @classmethod
    def validate_workspace_id(cls, value: str | None) -> str | None:
        return normalize_workspace_id(value) if value is not None else None

    @field_validator("goal")
    @classmethod
    def reject_secrets_in_goal(cls, value: str) -> str:
        if contains_likely_secret(value):
            raise ValueError("goal contains a likely secret; use environment variables instead")
        return value

    @field_validator("source_paths")
    @classmethod
    def unique_source_paths(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("source_paths cannot contain empty values")
        if len({item.casefold() for item in normalized}) != len(normalized):
            raise ValueError("source_paths cannot contain duplicates")
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

    @field_validator("quality_policies")
    @classmethod
    def unique_policies(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("quality_policies cannot contain duplicates")
        return value


class ImportedSourceFile(StrictModel):
    logical_path: str
    raw_sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(ge=0)


class PreparedAgentWorkspace(StrictModel):
    request_key: str = Field(pattern=SHA256_PATTERN)
    workspace_id: str
    run_id: str
    import_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    files: list[ImportedSourceFile]
    total_bytes: int = Field(ge=0)


class SourceImportSummary(StrictModel):
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    files: list[ImportedSourceFile]


class AgentCandidateSummary(StrictModel):
    artifact: str
    status: str
    partial: bool | None
    variants: list[ArtifactVariant]


class AgentNextAction(str, Enum):
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    WAIT = "wait"
    RETRY_SAME_REQUEST = "retry_same_request"
    INSPECT_ERRORS = "inspect_errors"
    NONE = "none"


class AgentRequestResult(StrictModel):
    schema_version: Literal["agentic-qa.harness.agent-request-result.v1"] = (
        "agentic-qa.harness.agent-request-result.v1"
    )
    request_key: str = Field(pattern=SHA256_PATTERN)
    workspace_id: str
    run_id: str
    status: str
    source_import: SourceImportSummary
    candidates: list[AgentCandidateSummary]
    next_action: AgentNextAction


class AgentRequestCapabilities(StrictModel):
    schema_version: Literal["agentic-qa.harness.agent-capabilities.v1"] = (
        "agentic-qa.harness.agent-capabilities.v1"
    )
    protocol_version: str = "agentic-qa.harness.agent-request.v1"
    artifacts: list[str] = Field(default_factory=lambda: list(ARTIFACT_TYPES))
    source_formats: list[str] = Field(default_factory=lambda: ["utf-8-text"])
    max_source_roots: int = 16
    max_files: int = 256
    max_recursion_depth: int = 16
    max_file_bytes: int = 16 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024
    execution_environment: str = "analysis-only"
    review_actions_exposed: list[str] = Field(default_factory=list)
