from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from harness.application.agent_request import AgentRequest, AgentRequestResult, AgentRequestService
from harness.application.ports import (
    ArtifactReviewRepository,
    QualityStrategyCatalog,
    RunEventRepository,
    WorkflowRunner,
    WorkspaceRepository,
)
from harness.domain.models import (
    ArtifactDiffResult,
    CreateWorkspaceCommand,
    GetArtifactDiffQuery,
    HarnessEvent,
    ResumeRunCommand,
    ReviewRunCommand,
    RunRef,
    RunSnapshot,
    StartRunCommand,
)


class HarnessApplication:
    def __init__(
        self,
        *,
        workspaces: WorkspaceRepository,
        runs: RunEventRepository,
        workflow: WorkflowRunner,
        quality_policies: QualityStrategyCatalog,
        artifacts: ArtifactReviewRepository | None = None,
        agent_requests: AgentRequestService | None = None,
    ) -> None:
        self._workspaces = workspaces
        self._runs = runs
        self._workflow = workflow
        self._quality_policies = quality_policies
        self._artifacts = artifacts
        self._agent_requests = agent_requests

    def create_workspace(self, command: CreateWorkspaceCommand) -> Path:
        self._quality_policies.require(command.quality_policies)
        return self._workspaces.init_workspace(
            command.workspace_id,
            quality_policies=command.quality_policies,
        )

    def start_run(self, command: StartRunCommand) -> RunSnapshot:
        self._workspaces.validate_execution_profile(command.workspace_id, command.execution_profile)
        return self._workflow.start(command)

    def stream_run(self, command: StartRunCommand) -> Iterator[HarnessEvent]:
        self._workspaces.validate_execution_profile(command.workspace_id, command.execution_profile)
        return self._workflow.stream(command)

    def get_run(self, ref: RunRef) -> RunSnapshot:
        return self._runs.load_snapshot(ref.workspace_id, ref.run_id)

    def get_run_read_only(self, ref: RunRef) -> RunSnapshot:
        return self._runs.load_snapshot_read_only(ref.workspace_id, ref.run_id)

    def get_artifact_diff(self, query: GetArtifactDiffQuery) -> ArtifactDiffResult:
        if self._artifacts is None:
            raise RuntimeError("artifact query repository is not configured")
        return self._artifacts.get_artifact_diff(query)

    def resume_run(self, command: ResumeRunCommand) -> RunSnapshot:
        snapshot = self._runs.load_snapshot(command.workspace_id, command.run_id)
        if snapshot.status not in {"planning", "running", "recoverable"}:
            raise ValueError(f"run 当前状态不可恢复: {snapshot.status}")
        self._workspaces.validate_execution_profile(
            command.workspace_id, snapshot.request.execution_profile
        )
        return self._workflow.resume(snapshot)

    def review_run(self, command: ReviewRunCommand) -> RunSnapshot:
        snapshot = self._runs.load_snapshot(command.workspace_id, command.run_id)
        if snapshot.status not in {"needs_human_review", "partial", "on_hold"}:
            raise ValueError(f"run 当前状态不可审核: {snapshot.status}")
        return self._workflow.review(snapshot, command.decision)

    def submit_agent_request(self, request: AgentRequest) -> AgentRequestResult:
        if self._agent_requests is None:
            raise RuntimeError("agent request service is not configured")
        return self._agent_requests.submit(request)
