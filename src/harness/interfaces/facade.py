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
    ApiPytestExportResult,
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
from harness.domain.schemas.knowledge import (
    KnowledgeDeleteCommand,
    KnowledgeDeleteResult,
    KnowledgeIndexResult,
    KnowledgeIndexRunCommand,
    KnowledgeMigrateResult,
    KnowledgeReindexCommand,
    KnowledgeReindexResult,
    KnowledgeStatus,
)
from harness.domain.schemas.local_config import LocalConfigCheckResult
from harness.domain.schemas.log_analysis import (
    AnalyzeFailureCommand,
    AnalyzeFailureResult,
    PrepareFailureReportCommand,
    PrepareFailureReportResult,
)
from harness.domain.schemas.log_evidence import CollectFailureLogsCommand, CollectFailureLogsResult
from harness.domain.schemas.trace_evidence import (
    CollectFailureEvidenceCommand,
    CollectFailureEvidenceResult,
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
        allowed_source_roots: list[Path | str] | None = None,
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
            allowed_source_roots=allowed_source_roots,
        )

    def create_workspace(self, command: CreateWorkspaceCommand) -> Path:
        return self._application.create_workspace(command)

    def check_local_config(self) -> LocalConfigCheckResult:
        return self._application.check_local_config()

    def knowledge_migrate(self) -> KnowledgeMigrateResult:
        return self._application.knowledge_migrate()

    def knowledge_status(self, workspace_id: str) -> KnowledgeStatus:
        return self._application.knowledge_status(workspace_id)

    def knowledge_index_run(self, command: KnowledgeIndexRunCommand) -> KnowledgeIndexResult:
        return self._application.knowledge_index_run(command)

    def knowledge_reindex(self, command: KnowledgeReindexCommand) -> KnowledgeReindexResult:
        return self._application.knowledge_reindex(command)

    def knowledge_delete(self, command: KnowledgeDeleteCommand) -> KnowledgeDeleteResult:
        return self._application.knowledge_delete(command)

    def prepare_api_scenario(self, command: ApiScenarioPrepareCommand) -> ApiScenarioPrepareResult:
        return self._application.prepare_api_scenario(command)

    def check_api_project(self, command: ApiProjectCheckCommand) -> ApiProjectCheckResult:
        return self._application.check_api_project(command)

    def start_run(self, command: StartRunCommand) -> RunSnapshot:
        return self._application.start_run(command)

    def stream_run(self, command: StartRunCommand) -> Iterator[HarnessEvent]:
        return self._application.stream_run(command)

    def get_run(self, ref: RunRef) -> RunSnapshot:
        return self._application.get_run(ref)

    def get_artifact_diff(self, query: GetArtifactDiffQuery) -> ArtifactDiffResult:
        return self._application.get_artifact_diff(query)

    def execute_api_cases(self, command: ExecuteApiCasesCommand) -> ExecutionEvidence:
        return self._application.execute_api_cases(command)

    def api_execution_profile(self, workspace: str, environment: str) -> ExecutionProfile:
        return self._application.api_execution_profile(workspace, environment)

    def run_api_scenario(self, command: RunApiScenarioCommand) -> RunApiScenarioResult:
        return self._application.run_api_scenario(command)

    def generate_api_allure_report(
        self, command: GenerateApiAllureReportCommand
    ) -> GenerateApiAllureReportResult:
        return self._application.generate_api_allure_report(command)

    def resume_api_cleanup(self, command: ResumeApiCleanupCommand) -> ResumeApiCleanupResult:
        return self._application.resume_api_cleanup(command)

    def collect_failure_logs(self, command: CollectFailureLogsCommand) -> CollectFailureLogsResult:
        return self._application.collect_failure_logs(command)

    def collect_failure_evidence(
        self, command: CollectFailureEvidenceCommand
    ) -> CollectFailureEvidenceResult:
        return self._application.collect_failure_evidence(command)

    def analyze_failure(self, command: AnalyzeFailureCommand) -> AnalyzeFailureResult:
        return self._application.analyze_failure(command)

    def prepare_failure_report(
        self, command: PrepareFailureReportCommand
    ) -> PrepareFailureReportResult:
        return self._application.prepare_failure_report(command)

    def export_api_pytest(self, command: ExportApiPytestCommand) -> ApiPytestExportResult:
        return self._application.export_api_pytest(command)

    def resume_run(self, command: ResumeRunCommand) -> RunSnapshot:
        return self._application.resume_run(command)

    def review_run(self, command: ReviewRunCommand) -> RunSnapshot:
        return self._application.review_run(command)
