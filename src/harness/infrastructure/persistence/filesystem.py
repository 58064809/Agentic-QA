from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.domain.models import (
    ArtifactCandidate,
    ExecutionEnvironmentPolicy,
    ExecutionProfile,
    HarnessEvent,
    RunSnapshot,
)
from harness.infrastructure.persistence.artifact_repository import (
    ArtifactReviewFilesystemRepository,
)
from harness.infrastructure.persistence.run_repository import RunEventFilesystemRepository
from harness.infrastructure.persistence.workspace_repository import WorkspaceFilesystemRepository


class FilesystemStore:
    """组合三个独立文件仓储，供基础设施工作流统一注入。"""

    def __init__(self, repo_root: Path | str) -> None:
        self.workspaces = WorkspaceFilesystemRepository(repo_root)
        self.runs = RunEventFilesystemRepository(self.workspaces)
        self.artifacts = ArtifactReviewFilesystemRepository(self.workspaces)
        self.repo_root = self.workspaces.repo_root
        self.root = self.workspaces.root

    def workspace_path(self, workspace: str) -> Path:
        return self.workspaces.workspace_path(workspace)

    def init_workspace(self, workspace: str, *, quality_policies: list[str]) -> Path:
        return self.workspaces.init_workspace(workspace, quality_policies=quality_policies)

    def require_workspace(self, workspace: str) -> Path:
        return self.workspaces.require_workspace(workspace)

    def workspace_config(self, workspace: str) -> dict[str, Any]:
        return self.workspaces.workspace_config(workspace)

    def validate_execution_profile(
        self, workspace: str, profile: ExecutionProfile
    ) -> ExecutionEnvironmentPolicy | None:
        return self.workspaces.validate_execution_profile(workspace, profile)

    def source_texts(self, workspace: str, limit: int = 100_000) -> list[tuple[str, str]]:
        return self.workspaces.source_texts(workspace, limit)

    def create_run(self, snapshot: RunSnapshot) -> None:
        self.runs.create_run(snapshot)

    def save_snapshot(self, snapshot: RunSnapshot) -> None:
        self.runs.save_snapshot(snapshot)

    def next_event_sequence(self, workspace: str, run_id: str) -> int:
        return self.runs.next_event_sequence(workspace, run_id)

    def append_event(self, workspace: str, event: HarnessEvent) -> None:
        self.runs.append_event(workspace, event)

    def write_tool_record(
        self, workspace: str, run_id: str, name: str, payload: dict[str, Any]
    ) -> Path:
        return self.runs.write_tool_record(workspace, run_id, name, payload)

    def tool_records(self, workspace: str, run_id: str) -> list[dict[str, Any]]:
        return self.runs.tool_records(workspace, run_id)

    def load_snapshot(self, workspace: str, run_id: str) -> RunSnapshot:
        return self.runs.load_snapshot(workspace, run_id)

    def write_candidate(self, **kwargs: Any) -> ArtifactCandidate:
        return self.artifacts.write_candidate(**kwargs)

    def ensure_candidate(self, **kwargs: Any) -> ArtifactCandidate:
        return self.artifacts.ensure_candidate(**kwargs)

    def load_candidate(self, **kwargs: Any) -> ArtifactCandidate | None:
        return self.artifacts.load_candidate(**kwargs)

    def write_review(self, snapshot: RunSnapshot, artifact: str, payload: dict[str, Any]) -> None:
        self.artifacts.write_review(snapshot, artifact, payload)

    def promote(self, snapshot: RunSnapshot, artifact: str) -> str:
        return self.artifacts.promote(snapshot, artifact)

    def promote_many(self, snapshot: RunSnapshot, artifacts: list[str]) -> dict[str, str]:
        return self.artifacts.promote_many(snapshot, artifacts)
