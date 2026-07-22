from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from harness.domain.models import (
    ExecutionProfile,
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


class ArtifactReviewRepository(Protocol):
    def promote_many(self, snapshot: RunSnapshot, artifacts: list[str]) -> dict[str, str]: ...

    def write_review(
        self, snapshot: RunSnapshot, artifact: str, payload: dict[str, object]
    ) -> None: ...


class CheckpointProvider(Protocol):
    def open(self) -> AbstractContextManager[Any]: ...


ToolHandler = Callable[[dict[str, Any]], Any]


class WorkflowRunner(Protocol):
    def start(self, command: StartRunCommand) -> RunSnapshot: ...

    def stream(self, command: StartRunCommand) -> Iterator[HarnessEvent]: ...

    def resume(self, snapshot: RunSnapshot) -> RunSnapshot: ...

    def review(self, snapshot: RunSnapshot, decision: ReviewDecision) -> RunSnapshot: ...
