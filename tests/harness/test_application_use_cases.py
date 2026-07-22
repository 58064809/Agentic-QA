from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from harness.application.use_cases import HarnessApplication
from harness.domain.models import (
    CreateWorkspaceCommand,
    ReviewDecision,
    ReviewRunCommand,
    RunSnapshot,
    StartRunCommand,
)
from harness.infrastructure.quality import QualityStrategyRegistry


@dataclass
class FakeRepositories:
    root: Path
    snapshots: dict[tuple[str, str], RunSnapshot] = field(default_factory=dict)

    def init_workspace(self, workspace: str, *, quality_policies: list[str]) -> Path:
        return self.root / "workspaces" / workspace

    def validate_execution_profile(self, _workspace: str, _profile: object) -> None:
        return None

    def load_snapshot(self, workspace: str, run_id: str) -> RunSnapshot:
        return self.snapshots[(workspace, run_id)]

    def save_snapshot(self, snapshot: RunSnapshot) -> None:
        self.snapshots[(snapshot.workspace_id, snapshot.run_id)] = snapshot


@dataclass
class FakeWorkflow:
    started: list[StartRunCommand] = field(default_factory=list)

    def start(self, command: StartRunCommand) -> RunSnapshot:
        self.started.append(command)
        return RunSnapshot(
            workspace_id=command.workspace_id,
            run_id="run-1",
            status="needs_human_review",
            request=command,
        )

    def stream(self, _command: StartRunCommand):
        return iter(())

    def resume(self, snapshot: RunSnapshot) -> RunSnapshot:
        return snapshot

    def review(self, snapshot: RunSnapshot, _decision: ReviewDecision) -> RunSnapshot:
        return snapshot


def _application(tmp_path: Path):
    repositories = FakeRepositories(tmp_path)
    workflow = FakeWorkflow()
    application = HarnessApplication(
        workspaces=repositories,
        runs=repositories,
        workflow=workflow,
        quality_policies=QualityStrategyRegistry(),
    )
    return application, repositories, workflow


def test_application_start_uses_workspace_qualified_command(tmp_path: Path) -> None:
    application, _, workflow = _application(tmp_path)
    command = StartRunCommand(workspace_id="demo", goal="test")

    snapshot = application.start_run(command)

    assert workflow.started == [command]
    assert snapshot.workspace_id == "demo"


def test_application_rejects_unknown_workspace_policy(tmp_path: Path) -> None:
    application, _, _ = _application(tmp_path)

    with pytest.raises(ValueError, match="unknown quality policies"):
        application.create_workspace(
            CreateWorkspaceCommand(workspace_id="demo", quality_policies=["missing"])
        )


def test_application_review_is_not_routed_through_resume(tmp_path: Path) -> None:
    application, repositories, _ = _application(tmp_path)
    command = StartRunCommand(workspace_id="demo", goal="test")
    snapshot = RunSnapshot(
        workspace_id="demo",
        run_id="run-review",
        status="needs_human_review",
        request=command,
    )
    repositories.save_snapshot(snapshot)

    reviewed = application.review_run(
        ReviewRunCommand(
            workspace_id="demo",
            run_id="run-review",
            decision=ReviewDecision(
                intent="hold",
                reason="manual hold",
                reviewed_by="qa-owner",
            ),
        )
    )

    assert reviewed is snapshot
