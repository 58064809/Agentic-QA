from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.application.quality import QualityReport
from harness.application.source import SourceBundle, SourceIngestionLimits
from harness.domain.models import (
    ApprovedArtifactVersion,
    ArtifactCandidate,
    ArtifactDiffResult,
    ExecutionEnvironmentPolicy,
    ExecutionProfile,
    GetArtifactDiffQuery,
    HarnessEvent,
    RunSnapshot,
)
from harness.infrastructure.persistence.artifact_repository import (
    ArtifactReviewFilesystemRepository,
)
from harness.infrastructure.persistence.run_repository import RunEventFilesystemRepository
from harness.infrastructure.persistence.source_bundle_repository import (
    SourceBundleFilesystemRepository,
)
from harness.infrastructure.persistence.workspace_repository import WorkspaceFilesystemRepository


class FilesystemStore:
    """组合三个独立文件仓储，供基础设施工作流统一注入。"""

    def __init__(
        self,
        repo_root: Path | str,
        *,
        source_limits: SourceIngestionLimits | None = None,
    ) -> None:
        self.workspaces = WorkspaceFilesystemRepository(repo_root)
        self.runs = RunEventFilesystemRepository(self.workspaces)
        self.artifacts = ArtifactReviewFilesystemRepository(self.workspaces)
        self.sources = SourceBundleFilesystemRepository(self.workspaces, source_limits)
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

    def create_source_bundle(self, workspace: str, run_id: str) -> SourceBundle:
        return self.sources.create_source_bundle(workspace, run_id)

    def load_source_bundle(self, workspace: str, run_id: str) -> SourceBundle:
        return self.sources.load_source_bundle(workspace, run_id)

    def create_run(self, snapshot: RunSnapshot) -> None:
        self.runs.create_run(snapshot)

    def save_snapshot(self, snapshot: RunSnapshot) -> None:
        self.runs.save_snapshot(snapshot)

    def next_event_sequence(self, workspace: str, run_id: str) -> int:
        return self.runs.next_event_sequence(workspace, run_id)

    def append_event(self, workspace: str, event: HarnessEvent) -> None:
        self.runs.append_event(workspace, event)

    def has_assessment_event(self, workspace: str, run_id: str, assessment_key: str) -> bool:
        return self.runs.has_assessment_event(workspace, run_id, assessment_key)

    def write_tool_record(
        self, workspace: str, run_id: str, name: str, payload: dict[str, Any]
    ) -> Path:
        return self.runs.write_tool_record(workspace, run_id, name, payload)

    def tool_records(self, workspace: str, run_id: str) -> list[dict[str, Any]]:
        return self.runs.tool_records(workspace, run_id)

    def load_snapshot(self, workspace: str, run_id: str) -> RunSnapshot:
        return self.runs.load_snapshot(workspace, run_id)

    def commit_candidate(self, **kwargs: Any) -> tuple[ArtifactCandidate, bool]:
        return self.artifacts.commit_candidate(**kwargs)

    def load_candidate(self, **kwargs: Any) -> ArtifactCandidate | None:
        return self.artifacts.load_candidate(**kwargs)

    def load_quality_report(self, candidate: ArtifactCandidate) -> QualityReport:
        return self.artifacts.load_quality_report(candidate)

    def get_artifact_diff(self, query: GetArtifactDiffQuery) -> ArtifactDiffResult:
        return self.artifacts.get_artifact_diff(query)

    def write_review(self, snapshot: RunSnapshot, artifact: str, payload: dict[str, Any]) -> None:
        self.artifacts.write_review(snapshot, artifact, payload)

    def promote_many(
        self, snapshot: RunSnapshot, versions: list[ApprovedArtifactVersion]
    ) -> dict[str, str]:
        return self.artifacts.promote_many(snapshot, versions)
