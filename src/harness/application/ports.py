from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from harness.application.quality import (
    NormalizationProposal,
    QualityComponentConfiguration,
    QualityContext,
    StrategyRequirements,
    StrategyResult,
)
from harness.application.source import SourceBundle
from harness.domain.models import (
    ApprovedArtifactVersion,
    ArtifactCandidate,
    ArtifactDiffResult,
    ExecutionProfile,
    GetArtifactDiffQuery,
    HarnessEvent,
    ReviewDecision,
    RunSnapshot,
    StartRunCommand,
)


class WorkspaceRepository(Protocol):
    def init_workspace(self, workspace: str, *, quality_policies: list[str]) -> Path: ...

    def validate_execution_profile(
        self, workspace: str, profile: ExecutionProfile
    ) -> object | None: ...


class RunEventRepository(Protocol):
    def load_snapshot(self, workspace: str, run_id: str) -> RunSnapshot: ...

    def save_snapshot(self, snapshot: RunSnapshot) -> None: ...

    def next_event_sequence(self, workspace: str, run_id: str) -> int: ...

    def append_event(self, workspace: str, event: HarnessEvent) -> None: ...


class ArtifactReviewRepository(Protocol):
    def get_artifact_diff(self, query: GetArtifactDiffQuery) -> ArtifactDiffResult: ...
    def promote_many(
        self, snapshot: RunSnapshot, versions: list[ApprovedArtifactVersion]
    ) -> dict[str, str]: ...

    def load_quality_report(self, candidate: ArtifactCandidate) -> object: ...

    def write_review(
        self, snapshot: RunSnapshot, artifact: str, payload: dict[str, object]
    ) -> None: ...


class CheckpointProvider(Protocol):
    def open(self) -> AbstractContextManager[Any]: ...


ToolHandler = Callable[[dict[str, Any]], Any]


class SourceBundleRepository(Protocol):
    def create_source_bundle(self, workspace: str, run_id: str) -> SourceBundle: ...

    def load_source_bundle(self, workspace: str, run_id: str) -> SourceBundle: ...


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
    def start(self, command: StartRunCommand) -> RunSnapshot: ...

    def stream(self, command: StartRunCommand) -> Iterator[HarnessEvent]: ...

    def resume(self, snapshot: RunSnapshot) -> RunSnapshot: ...

    def review(self, snapshot: RunSnapshot, decision: ReviewDecision) -> RunSnapshot: ...
