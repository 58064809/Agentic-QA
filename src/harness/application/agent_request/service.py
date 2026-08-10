from __future__ import annotations

from harness.application.agent_request.models import (
    AgentCandidateSummary,
    AgentNextAction,
    AgentRequest,
    AgentRequestResult,
    PreparedAgentWorkspace,
    SourceImportSummary,
)
from harness.application.ports import (
    ApiScenarioSourceCatalog,
    ManagedAgentWorkspaceProvisioner,
    QualityStrategyCatalog,
    RunEventRepository,
    WorkflowRunner,
)
from harness.domain.models import (
    ApiScenarioSourceSummary,
    ExecutionEnvironmentPolicy,
    ExecutionProfile,
    RunSnapshot,
    StartRunCommand,
)


class AgentRequestService:
    def __init__(
        self,
        *,
        provisioner: ManagedAgentWorkspaceProvisioner,
        runs: RunEventRepository,
        workflow: WorkflowRunner,
        quality_policies: QualityStrategyCatalog,
        api_scenario_sources: ApiScenarioSourceCatalog | None = None,
    ) -> None:
        self._provisioner = provisioner
        self._runs = runs
        self._workflow = workflow
        self._quality_policies = quality_policies
        self._api_scenario_sources = api_scenario_sources

    def submit(self, request: AgentRequest) -> AgentRequestResult:
        return self._submit(request, generation_mode="standard", execution_environments={})

    def submit_api_fast(
        self,
        request: AgentRequest,
        *,
        execution_environments: dict[str, ExecutionEnvironmentPolicy],
        api_project_binding: dict[str, str],
    ) -> AgentRequestResult:
        if request.expected_artifacts != ["api_test_draft"]:
            raise ValueError("api_fast only supports api_test_draft")
        if len(execution_environments) != 1:
            raise ValueError("api_fast requires exactly one execution environment policy")
        return self._submit(
            request,
            generation_mode="api_fast",
            execution_environments=execution_environments,
            api_project_binding=api_project_binding,
        )

    def _submit(
        self,
        request: AgentRequest,
        *,
        generation_mode: str,
        execution_environments: dict[str, ExecutionEnvironmentPolicy],
        api_project_binding: dict[str, str] | None = None,
    ) -> AgentRequestResult:
        self._quality_policies.require(request.quality_policies)
        prepared = (
            self._provisioner.prepare(request)
            if generation_mode == "standard"
            else self._provisioner.prepare(
                request,
                generation_mode=generation_mode,
                execution_environments=execution_environments,
                api_project_binding=api_project_binding,
            )
        )
        command = StartRunCommand(
            workspace_id=prepared.workspace_id,
            goal=request.goal,
            expected_artifacts=request.expected_artifacts,
            execution_profile=ExecutionProfile(),
            generation_mode=generation_mode,
        )
        with self._provisioner.request_lock(prepared):
            snapshot = self._load_existing(prepared)
            if snapshot is None:
                snapshot = self._workflow.start(command, run_id=prepared.run_id)
            else:
                self._validate_existing(snapshot, command)
                if snapshot.status == "recoverable":
                    snapshot = self._workflow.resume(snapshot)
        return self._result(prepared, snapshot)

    def _load_existing(self, prepared: PreparedAgentWorkspace) -> RunSnapshot | None:
        try:
            return self._runs.load_snapshot(prepared.workspace_id, prepared.run_id)
        except FileNotFoundError:
            return None

    def inspect_api_sources(self, workspace: str, run_id: str) -> ApiScenarioSourceSummary:
        if self._api_scenario_sources is None:
            raise RuntimeError("API scenario source catalog is not configured")
        return self._api_scenario_sources.inspect(workspace, run_id)

    @staticmethod
    def _validate_existing(snapshot: RunSnapshot, command: StartRunCommand) -> None:
        if snapshot.request != command:
            raise RuntimeError("托管 request 的确定性 run 与已存在 command 不一致")

    @staticmethod
    def _result(
        prepared: PreparedAgentWorkspace,
        snapshot: RunSnapshot,
    ) -> AgentRequestResult:
        if snapshot.status in {"needs_human_review", "on_hold"}:
            next_action = AgentNextAction.HUMAN_REVIEW_REQUIRED
        elif snapshot.status == "partial":
            next_action = AgentNextAction.INSPECT_ERRORS
        elif snapshot.status in {"planning", "running"}:
            next_action = AgentNextAction.WAIT
        elif snapshot.status == "recoverable":
            next_action = AgentNextAction.RETRY_SAME_REQUEST
        elif snapshot.status == "failed":
            next_action = AgentNextAction.INSPECT_ERRORS
        else:
            next_action = AgentNextAction.NONE
        return AgentRequestResult(
            request_key=prepared.request_key,
            workspace_id=prepared.workspace_id,
            run_id=prepared.run_id,
            status=snapshot.status,
            source_import=SourceImportSummary(
                file_count=len(prepared.files),
                total_bytes=prepared.total_bytes,
                manifest_sha256=prepared.import_manifest_sha256,
                files=prepared.files,
            ),
            candidates=[
                AgentCandidateSummary(
                    artifact=candidate.artifact,
                    status=candidate.status,
                    partial=candidate.partial,
                    variants=[version.variant for version in candidate.versions],
                )
                for candidate in snapshot.candidates
            ],
            next_action=next_action,
        )
