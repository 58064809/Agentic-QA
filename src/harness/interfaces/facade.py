from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from harness.application.model_port import ModelGateway
from harness.application.ports import CheckpointProvider
from harness.application.use_cases import HarnessApplication
from harness.bootstrap import build_application
from harness.domain.budget import BudgetLimits
from harness.domain.models import (
    CreateWorkspaceCommand,
    HarnessEvent,
    ResumeRunCommand,
    ReviewRunCommand,
    RunRef,
    RunSnapshot,
    StartRunCommand,
)
from harness.infrastructure.manifests.registry import AgentRegistry, SkillRegistry, ToolRegistry
from harness.infrastructure.quality import QualityStrategyRegistry


class Harness:
    """Synchronous v2 facade; all behavior is delegated to application use cases."""

    def __init__(
        self,
        repo_root: Path | str = ".",
        *,
        model_gateway: ModelGateway | None = None,
        budget_limits: BudgetLimits | None = None,
        agent_registry: AgentRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
        quality_strategy_registry: QualityStrategyRegistry | None = None,
        checkpoint_provider: CheckpointProvider | None = None,
        tool_handlers: dict[str, Any] | None = None,
        application: HarnessApplication | None = None,
    ) -> None:
        self._application = application or build_application(
            repo_root,
            model_gateway=model_gateway,
            budget_limits=budget_limits,
            agent_registry=agent_registry,
            skill_registry=skill_registry,
            tool_registry=tool_registry,
            quality_strategy_registry=quality_strategy_registry,
            checkpoint_provider=checkpoint_provider,
            tool_handlers=tool_handlers,
        )

    def create_workspace(self, command: CreateWorkspaceCommand) -> Path:
        return self._application.create_workspace(command)

    def start_run(self, command: StartRunCommand) -> RunSnapshot:
        return self._application.start_run(command)

    def stream_run(self, command: StartRunCommand) -> Iterator[HarnessEvent]:
        return self._application.stream_run(command)

    def get_run(self, ref: RunRef) -> RunSnapshot:
        return self._application.get_run(ref)

    def resume_run(self, command: ResumeRunCommand) -> RunSnapshot:
        return self._application.resume_run(command)

    def review_run(self, command: ReviewRunCommand) -> RunSnapshot:
        return self._application.review_run(command)
