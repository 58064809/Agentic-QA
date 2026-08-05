from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from harness.application.agent_request.models import AgentRequest, PreparedAgentWorkspace
from harness.application.quality import (
    NormalizationProposal,
    QualityComponentConfiguration,
    QualityContext,
    StrategyRequirements,
    StrategyResult,
)
from harness.application.source import SourceBundle
from harness.domain.models import (
    ApiPytestExportResult,
    ApiScenarioSourceSummary,
    ApprovedArtifactVersion,
    ArtifactCandidate,
    ArtifactDiffResult,
    ExecuteApiCasesCommand,
    ExecutionEnvironmentPolicy,
    ExecutionProfile,
    ExportApiPytestCommand,
    GetArtifactDiffQuery,
    HarnessEvent,
    ReviewDecision,
    RunApiScenarioCommand,
    RunSnapshot,
    StartRunCommand,
)
from harness.domain.schemas.api_scenario import RunApiScenarioResult
from harness.domain.schemas.execution_evidence import ExecutionEvidence


class WorkspaceRepository(Protocol):
    def init_workspace(self, workspace: str, *, quality_policies: list[str]) -> Path: ...

    def validate_execution_profile(
        self, workspace: str, profile: ExecutionProfile
    ) -> object | None: ...


class ApiAutomationService(Protocol):
    def execute(self, command: ExecuteApiCasesCommand) -> ExecutionEvidence: ...

    def export_pytest(self, command: ExportApiPytestCommand) -> ApiPytestExportResult: ...


class ApiScenarioRunner(Protocol):
    def run(self, command: RunApiScenarioCommand) -> RunApiScenarioResult: ...


class ManagedAgentWorkspaceProvisioner(Protocol):
    def prepare(
        self,
        request: AgentRequest,
        *,
        generation_mode: str = "standard",
        execution_environments: dict[str, ExecutionEnvironmentPolicy] | None = None,
    ) -> PreparedAgentWorkspace: ...

    def request_lock(self, prepared: PreparedAgentWorkspace) -> AbstractContextManager[None]: ...


class RunEventRepository(Protocol):
    def load_snapshot(self, workspace: str, run_id: str) -> RunSnapshot: ...

    def load_snapshot_read_only(self, workspace: str, run_id: str) -> RunSnapshot: ...

    def save_snapshot(self, snapshot: RunSnapshot) -> None: ...

    def next_event_sequence(self, workspace: str, run_id: str) -> int: ...

    def append_event(self, workspace: str, event: HarnessEvent) -> None: ...


class ArtifactReviewRepository(Protocol):
    def get_artifact_diff(self, query: GetArtifactDiffQuery) -> ArtifactDiffResult: ...
    def load_quality_report(self, candidate: ArtifactCandidate) -> object: ...

    def write_review(
        self, snapshot: RunSnapshot, artifact: str, payload: dict[str, object]
    ) -> None: ...

    def publish_review(
        self,
        snapshot: RunSnapshot,
        versions: list[ApprovedArtifactVersion],
        review_records: dict[str, dict[str, object]],
    ) -> None: ...


class CheckpointProvider(Protocol):
    def open(self) -> AbstractContextManager[Any]: ...


ToolHandler = Callable[[dict[str, Any]], Any]


class SourceBundleRepository(Protocol):
    def create_source_bundle(self, workspace: str, run_id: str) -> SourceBundle: ...

    def load_source_bundle(self, workspace: str, run_id: str) -> SourceBundle: ...


class ApiScenarioSourceCatalog(Protocol):
    def inspect(self, workspace: str, run_id: str) -> ApiScenarioSourceSummary: ...


class QualityStrategy(Protocol):
    name: str
    version: str
    requirements: StrategyRequirements
    configuration: QualityComponentConfiguration

    def evaluate(self, context: QualityContext, content: str) -> StrategyResult: ...


class ArtifactNormalizer(Protocol):
    name: str
    version: str
    configuration: QualityComponentConfiguration

    def propose(self, context: QualityContext, content: str) -> NormalizationProposal: ...


class QualityStrategyCatalog(Protocol):
    def require(self, names: list[str]) -> tuple[QualityStrategy, ...]: ...

    def normalizers(self) -> tuple[ArtifactNormalizer, ...]: ...


class WorkflowRunner(Protocol):
    def start(self, command: StartRunCommand, *, run_id: str | None = None) -> RunSnapshot: ...

    def stream(self, command: StartRunCommand) -> Iterator[HarnessEvent]: ...

    def resume(self, snapshot: RunSnapshot) -> RunSnapshot: ...

    def review(self, snapshot: RunSnapshot, decision: ReviewDecision) -> RunSnapshot: ...
