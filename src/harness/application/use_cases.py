from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from harness.application.agent_request import AgentRequest, AgentRequestResult, AgentRequestService
from harness.application.ports import (
    ApiAutomationService,
    ArtifactReviewRepository,
    QualityStrategyCatalog,
    RunEventRepository,
    WorkflowRunner,
    WorkspaceRepository,
)
from harness.domain.models import (
    ApiPytestExportResult,
    ApiScenarioCandidateSummary,
    ApiScenarioPrepareCommand,
    ApiScenarioPrepareResult,
    ArtifactDiffResult,
    CreateWorkspaceCommand,
    ExecuteApiCasesCommand,
    ExportApiPytestCommand,
    GetArtifactDiffQuery,
    HarnessEvent,
    ResumeRunCommand,
    ReviewRunCommand,
    RunRef,
    RunSnapshot,
    StartRunCommand,
)
from harness.domain.schemas.execution_evidence import ExecutionEvidence


class HarnessApplication:
    def __init__(
        self,
        *,
        workspaces: WorkspaceRepository,
        runs: RunEventRepository,
        workflow: WorkflowRunner,
        quality_policies: QualityStrategyCatalog,
        api_automation: ApiAutomationService | None = None,
        artifacts: ArtifactReviewRepository | None = None,
        agent_requests: AgentRequestService | None = None,
    ) -> None:
        self._workspaces = workspaces
        self._runs = runs
        self._workflow = workflow
        self._quality_policies = quality_policies
        self._api_automation = api_automation
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

    def execute_api_cases(self, command: ExecuteApiCasesCommand) -> ExecutionEvidence:
        if self._api_automation is None:
            raise RuntimeError("API automation service is not configured")
        return self._api_automation.execute(command)

    def export_api_pytest(self, command: ExportApiPytestCommand) -> ApiPytestExportResult:
        if self._api_automation is None:
            raise RuntimeError("API automation service is not configured")
        return self._api_automation.export_pytest(command)

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

    def prepare_api_scenario(self, command: ApiScenarioPrepareCommand) -> ApiScenarioPrepareResult:
        if self._agent_requests is None:
            raise RuntimeError("API scenario prepare is not configured")
        result = self._agent_requests.submit_api_fast(
            AgentRequest(
                request_id=command.request_id,
                workspace_id=command.workspace_id,
                goal=command.goal,
                source_paths=[command.source_directory],
                expected_artifacts=["api_test_draft"],
                quality_policies=command.quality_policies,
            ),
            execution_environments={command.environment: command.execution_policy},
        )
        sources = self._agent_requests.inspect_api_sources(result.workspace_id, result.run_id)
        snapshot = self._runs.load_snapshot(result.workspace_id, result.run_id)
        candidates = [item for item in snapshot.candidates if item.artifact == "api_test_draft"]
        if len(candidates) != 1:
            raise RuntimeError("API scenario prepare requires exactly one API Candidate")
        candidate = candidates[0]
        if candidate.quality_report_path is None:
            raise RuntimeError("API Candidate has no quality report")
        return ApiScenarioPrepareResult(
            request_key=result.request_key,
            workspace_id=result.workspace_id,
            run_id=result.run_id,
            status=result.status,
            environment=command.environment,
            sources=sources,
            candidate=ApiScenarioCandidateSummary(
                status=candidate.status,
                partial=bool(candidate.partial),
                versions=candidate.versions,
                candidate_path=candidate.path,
                quality_report_path=candidate.quality_report_path,
                generation_report_path=candidate.generation_report_path,
            ),
            next_action="human_review_required",
        )
