from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.application.agent_request import AgentRequestService
from harness.application.model_port import ModelGateway
from harness.application.ports import CheckpointProvider
from harness.application.use_cases import HarnessApplication
from harness.domain.budget import BudgetLimits
from harness.infrastructure.api_automation import FilesystemApiAutomationService
from harness.infrastructure.api_project import FilesystemApiProjectChecker
from harness.infrastructure.api_scenario_run import FilesystemApiScenarioRunService
from harness.infrastructure.api_scenario_sources import FilesystemApiScenarioSourceCatalog
from harness.infrastructure.failure_logs import FilesystemFailureLogService
from harness.infrastructure.llm.gateway import model_gateway_from_config
from harness.infrastructure.local_config import FilesystemLocalConfigLoader
from harness.infrastructure.manifests.registry import AgentRegistry, SkillRegistry, ToolRegistry
from harness.infrastructure.persistence.agent_workspace_provisioner import (
    ManagedAgentWorkspaceFilesystemProvisioner,
)
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.persistence.postgres_checkpoint import (
    CheckpointPostgresConfig,
    PostgresCheckpointProvider,
)
from harness.infrastructure.quality import QualityStrategyRegistry
from harness.infrastructure.quality.declarative import DeclarativeQualityStrategy
from harness.infrastructure.quality.generic import GenericArtifactStrategy
from harness.infrastructure.quality.normalization import SafeMarkdownNormalizer
from harness.infrastructure.workflow.engine import HarnessEngine
from harness.infrastructure.workflow.runner import LangGraphWorkflowRunner

LOCAL_REQUIREMENTS_RELATIVE_PATH = Path("local-sources") / "requirements"


def ensure_local_requirements_root(repo_root: Path | str) -> Path:
    """Return the repository-local requirement inbox, creating it when absent."""
    path = Path(repo_root).resolve() / LOCAL_REQUIREMENTS_RELATIVE_PATH
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise NotADirectoryError(f"本地需求路径不是目录: {path}")
    return path


def agent_source_roots(
    repo_root: Path | str,
    additional_roots: list[Path | str] | None = None,
) -> list[Path]:
    """Build the MCP/Agent Request allowlist with the local inbox always included."""
    roots = [ensure_local_requirements_root(repo_root)]
    seen = {str(roots[0]).casefold()}
    for item in additional_roots or []:
        path = Path(item)
        key = str(path.resolve()).casefold()
        if key not in seen:
            roots.append(path)
            seen.add(key)
    return roots


def build_application(
    repo_root: Path | str,
    *,
    model_gateway: ModelGateway | None = None,
    budget_limits: BudgetLimits | None = None,
    agent_registry: AgentRegistry | None = None,
    skill_registry: SkillRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
    quality_strategy_registry: QualityStrategyRegistry | None = None,
    checkpoint_provider: CheckpointProvider | None = None,
    tool_handlers: dict[str, Any] | None = None,
    allowed_source_roots: list[Path | str] | None = None,
) -> HarnessApplication:
    local_loader = FilesystemLocalConfigLoader(repo_root)
    local_config = local_loader.load_required()
    ensure_local_requirements_root(repo_root)
    store = FilesystemStore(repo_root)
    tools = tool_registry or ToolRegistry.builtin()
    skills = skill_registry or SkillRegistry.builtin()
    agents = agent_registry or AgentRegistry.builtin(skills=skills, tools=tools)
    policies = quality_strategy_registry or QualityStrategyRegistry()
    if GenericArtifactStrategy.name not in policies.strategies:
        policies.register(GenericArtifactStrategy())
    declarative_manifest = (
        Path(__file__).resolve().parent / "manifests" / "quality" / "city-opening-rewards.yml"
    )
    declarative = DeclarativeQualityStrategy.from_manifest(declarative_manifest)
    if declarative.name not in policies.strategies:
        policies.register(declarative)
    if not policies.normalizers():
        policies.register_normalizer(SafeMarkdownNormalizer())
    engine = HarnessEngine(
        store=store,
        agents=agents,
        skills=skills,
        tools=tools,
        quality_policies=policies,
        checkpoint_provider=checkpoint_provider
        or PostgresCheckpointProvider(
            CheckpointPostgresConfig(
                host=local_config.postgres.host,
                port=local_config.postgres.port,
                database=local_config.postgres.database,
                user=local_config.postgres.user,
                password=local_config.postgres.password,
                connect_timeout_seconds=local_config.postgres.connect_timeout_seconds,
            )
        ),
        model=model_gateway or model_gateway_from_config(local_config.model),
        local_config=local_config,
        limits=budget_limits,
        tool_handlers=tool_handlers,
    )
    workflow = LangGraphWorkflowRunner(store=store, engine=engine)
    agent_requests = None
    configured_source_roots = [
        Path(repo_root).resolve() / item
        for item in local_config.workspace_defaults.additional_source_roots
    ]
    if allowed_source_roots is not None:
        agent_requests = AgentRequestService(
            provisioner=ManagedAgentWorkspaceFilesystemProvisioner(
                store.workspaces,
                allowed_source_roots=[*configured_source_roots, *allowed_source_roots],
            ),
            runs=store,
            workflow=workflow,
            quality_policies=policies,
            api_scenario_sources=FilesystemApiScenarioSourceCatalog(store),
        )
    api_automation = FilesystemApiAutomationService(store, local_loader)
    return HarnessApplication(
        workspaces=store,
        runs=store,
        workflow=workflow,
        quality_policies=policies,
        api_automation=api_automation,
        api_scenario_runner=FilesystemApiScenarioRunService(store, api_automation),
        api_project_checker=FilesystemApiProjectChecker(repo_root),
        local_config_checker=local_loader,
        local_config=local_config,
        artifacts=store,
        agent_requests=agent_requests,
        failure_logs=FilesystemFailureLogService(store, local_config),
    )
