from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.application.model_port import ModelGateway
from harness.application.ports import CheckpointProvider
from harness.application.use_cases import HarnessApplication
from harness.domain.budget import BudgetLimits
from harness.domain.quality import QualityPolicyRegistry
from harness.domain.quality.city_policy import CityOpeningRewardsPolicy
from harness.domain.quality.generic import GenericArtifactPolicy
from harness.infrastructure.llm.gateway import model_gateway_from_env
from harness.infrastructure.manifests.registry import AgentRegistry, SkillRegistry, ToolRegistry
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.persistence.postgres_checkpoint import PostgresCheckpointProvider
from harness.infrastructure.workflow.engine import HarnessEngine
from harness.infrastructure.workflow.runner import LangGraphWorkflowRunner


def build_application(
    repo_root: Path | str,
    *,
    model_gateway: ModelGateway | None = None,
    budget_limits: BudgetLimits | None = None,
    agent_registry: AgentRegistry | None = None,
    skill_registry: SkillRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
    quality_policy_registry: QualityPolicyRegistry | None = None,
    checkpoint_provider: CheckpointProvider | None = None,
    tool_handlers: dict[str, Any] | None = None,
) -> HarnessApplication:
    store = FilesystemStore(repo_root)
    tools = tool_registry or ToolRegistry.builtin()
    skills = skill_registry or SkillRegistry.builtin()
    agents = agent_registry or AgentRegistry.builtin(skills=skills, tools=tools)
    policies = quality_policy_registry or QualityPolicyRegistry()
    if GenericArtifactPolicy.name not in policies.policies:
        policies.register(GenericArtifactPolicy())
    if CityOpeningRewardsPolicy.name not in policies.policies:
        policies.register(CityOpeningRewardsPolicy())
    engine = HarnessEngine(
        store=store,
        agents=agents,
        skills=skills,
        tools=tools,
        quality_policies=policies,
        checkpoint_provider=checkpoint_provider or PostgresCheckpointProvider(),
        model=model_gateway or model_gateway_from_env(),
        limits=budget_limits,
        tool_handlers=tool_handlers,
    )
    workflow = LangGraphWorkflowRunner(store=store, engine=engine)
    return HarnessApplication(
        workspaces=store,
        runs=store,
        workflow=workflow,
        quality_policies=policies,
    )
