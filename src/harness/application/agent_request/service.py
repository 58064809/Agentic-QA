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
    ManagedAgentWorkspaceProvisioner,
    QualityStrategyCatalog,
    RunEventRepository,
    WorkflowRunner,
)
from harness.domain.models import ExecutionProfile, RunSnapshot, StartRunCommand


class AgentRequestService:
    def __init__(
        self,
        *,
        provisioner: ManagedAgentWorkspaceProvisioner,
        runs: RunEventRepository,
        workflow: WorkflowRunner,
        quality_policies: QualityStrategyCatalog,
    ) -> None:
        self._provisioner = provisioner
        self._runs = runs
        self._workflow = workflow
        self._quality_policies = quality_policies

    def submit(self, request: AgentRequest) -> AgentRequestResult:
        self._quality_policies.require(request.quality_policies)
        prepared = self._provisioner.prepare(request)
        command = StartRunCommand(
            workspace_id=prepared.workspace_id,
            goal=request.goal,
            expected_artifacts=request.expected_artifacts,
            execution_profile=ExecutionProfile(),
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

    @staticmethod
    def _validate_existing(snapshot: RunSnapshot, command: StartRunCommand) -> None:
        if snapshot.request != command:
            raise RuntimeError("托管 request 的确定性 run 与已存在 command 不一致")

    @staticmethod
    def _result(
        prepared: PreparedAgentWorkspace,
        snapshot: RunSnapshot,
    ) -> AgentRequestResult:
        if snapshot.status in {"needs_human_review", "partial", "on_hold"}:
            next_action = AgentNextAction.HUMAN_REVIEW_REQUIRED
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
