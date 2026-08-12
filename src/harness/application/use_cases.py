from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from harness.application.agent_request import AgentRequest, AgentRequestResult, AgentRequestService
from harness.application.ports import (
    ApiAutomationService,
    ApiProjectChecker,
    ApiScenarioRunner,
    ArtifactReviewRepository,
    FailureLogService,
    LocalConfigChecker,
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
    ExecutionProfile,
    ExportApiPytestCommand,
    GetArtifactDiffQuery,
    HarnessEvent,
    ResumeRunCommand,
    ReviewRunCommand,
    RunApiScenarioCommand,
    RunRef,
    RunSnapshot,
    StartRunCommand,
)
from harness.domain.schemas.api_execution_reporting import (
    GenerateApiAllureReportCommand,
    GenerateApiAllureReportResult,
    ResumeApiCleanupCommand,
    ResumeApiCleanupResult,
)
from harness.domain.schemas.api_project import ApiProjectCheckCommand, ApiProjectCheckResult
from harness.domain.schemas.api_scenario import RunApiScenarioResult
from harness.domain.schemas.execution_evidence import ExecutionEvidence
from harness.domain.schemas.local_config import AgenticQaLocalConfig, LocalConfigCheckResult
from harness.domain.schemas.log_analysis import (
    AnalyzeFailureCommand,
    AnalyzeFailureResult,
    PrepareFailureReportCommand,
    PrepareFailureReportResult,
)
from harness.domain.schemas.log_evidence import CollectFailureLogsCommand, CollectFailureLogsResult


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
        api_scenario_runner: ApiScenarioRunner | None = None,
        api_project_checker: ApiProjectChecker | None = None,
        local_config_checker: LocalConfigChecker | None = None,
        local_config: AgenticQaLocalConfig | None = None,
        failure_logs: FailureLogService | None = None,
    ) -> None:
        self._workspaces = workspaces
        self._runs = runs
        self._workflow = workflow
        self._quality_policies = quality_policies
        self._api_automation = api_automation
        self._artifacts = artifacts
        self._agent_requests = agent_requests
        self._api_scenario_runner = api_scenario_runner
        self._api_project_checker = api_project_checker
        self._local_config_checker = local_config_checker
        self._local_config = local_config
        self._failure_logs = failure_logs

    def check_local_config(self) -> LocalConfigCheckResult:
        if self._local_config_checker is None:
            raise RuntimeError("local configuration checker is not configured")
        return self._local_config_checker.check()

    def create_workspace(self, command: CreateWorkspaceCommand) -> Path:
        defaults = (
            self._local_config.workspace_defaults.quality_policies if self._local_config else []
        )
        policies = list(dict.fromkeys([*defaults, *command.quality_policies]))
        self._quality_policies.require(policies)
        return self._workspaces.init_workspace(
            command.workspace_id,
            quality_policies=policies,
        )

    def start_run(self, command: StartRunCommand) -> RunSnapshot:
        if "api_test_draft" in command.expected_artifacts:
            raise ValueError(
                "API test generation requires project preflight; use api prepare instead"
            )
        self._workspaces.validate_execution_profile(command.workspace_id, command.execution_profile)
        return self._workflow.start(command)

    def stream_run(self, command: StartRunCommand) -> Iterator[HarnessEvent]:
        if "api_test_draft" in command.expected_artifacts:
            raise ValueError(
                "API test generation requires project preflight; use api prepare instead"
            )
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

    def api_execution_profile(self, workspace: str, environment: str) -> ExecutionProfile:
        if self._api_automation is None:
            raise RuntimeError("API automation service is not configured")
        return self._api_automation.execution_profile(workspace, environment)

    def run_api_scenario(self, command: RunApiScenarioCommand) -> RunApiScenarioResult:
        if self._api_scenario_runner is None:
            raise RuntimeError("API scenario runner is not configured")
        return self._api_scenario_runner.run(command)

    def generate_api_allure_report(
        self, command: GenerateApiAllureReportCommand
    ) -> GenerateApiAllureReportResult:
        if self._api_scenario_runner is None:
            raise RuntimeError("API scenario runner is not configured")
        return self._api_scenario_runner.generate_allure_report(command)

    def resume_api_cleanup(self, command: ResumeApiCleanupCommand) -> ResumeApiCleanupResult:
        if self._api_scenario_runner is None:
            raise RuntimeError("API scenario runner is not configured")
        return self._api_scenario_runner.resume_cleanup(command)

    def collect_failure_logs(self, command: CollectFailureLogsCommand) -> CollectFailureLogsResult:
        if self._failure_logs is None:
            raise RuntimeError("failure log collection is not configured")
        return self._failure_logs.collect(command)

    def analyze_failure(self, command: AnalyzeFailureCommand) -> AnalyzeFailureResult:
        if self._failure_logs is None:
            raise RuntimeError("failure analysis is not configured")
        return self._failure_logs.analyze(command)

    def prepare_failure_report(
        self, command: PrepareFailureReportCommand
    ) -> PrepareFailureReportResult:
        if self._failure_logs is None:
            raise RuntimeError("failure report preparation is not configured")
        return self._failure_logs.prepare_report(command)

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
        if "api_test_draft" in request.expected_artifacts:
            raise ValueError(
                "API test generation requires project preflight; use api prepare instead"
            )
        return self._agent_requests.submit(request)

    def check_api_project(self, command: ApiProjectCheckCommand) -> ApiProjectCheckResult:
        if self._api_project_checker is None:
            raise RuntimeError("API project checker is not configured")
        return self._api_project_checker.check(command)

    def prepare_api_scenario(self, command: ApiScenarioPrepareCommand) -> ApiScenarioPrepareResult:
        if self._agent_requests is None:
            raise RuntimeError("API scenario prepare is not configured")
        if self._api_project_checker is None:
            raise RuntimeError("API project checker is not configured")
        preflight = self._api_project_checker.check(
            ApiProjectCheckCommand(
                source_directory=command.source_directory,
                environment=command.environment,
                execution_policy=command.execution_policy,
            )
        )
        if not preflight.ready or preflight.execution_policy is None:
            details = "; ".join(
                f"{issue.code} at {issue.location}: {issue.remediation}"
                for issue in preflight.issues
            )
            raise ValueError(f"API project preflight failed: {details}")
        execution_policy = preflight.execution_policy
        defaults = (
            self._local_config.workspace_defaults.quality_policies if self._local_config else []
        )
        quality_policies = list(dict.fromkeys([*defaults, *command.quality_policies]))
        result = self._agent_requests.submit_api_fast(
            AgentRequest(
                request_id=command.request_id,
                workspace_id=command.workspace_id,
                goal=command.goal,
                source_paths=[command.source_directory],
                expected_artifacts=["api_test_draft"],
                quality_policies=quality_policies,
            ),
            execution_environments={command.environment: execution_policy},
            api_project_binding={
                "service": str(preflight.service),
                "environment": command.environment,
                "structural_sha256": str(preflight.structural_sha256),
            },
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
