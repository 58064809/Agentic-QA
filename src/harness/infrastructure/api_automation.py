from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from harness.domain.models import (
    ApiAuthentication,
    ApiIsolationPolicy,
    ApiOperationPolicy,
    ApiPytestExportResult,
    ExecuteApiCasesCommand,
    ExecutionProfile,
    ExportApiPytestCommand,
)
from harness.domain.schemas.api_test_cases import (
    ApiCleanupStep,
    ApiTestCase,
    ApiTestCasesDraft,
    api_execution_case_ids,
    validate_api_case_runtime_definitions,
    validate_api_cleanup_policy,
)
from harness.domain.schemas.execution_evidence import ExecutionEvidence
from harness.infrastructure.api_published_source import PublishedApiSourceResolver
from harness.infrastructure.local_config import FilesystemLocalConfigLoader, ResolvedApiProject
from harness.infrastructure.persistence.common import atomic_text
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.tools.api_execution import (
    execute_api_cases,
    validate_api_execution_preflight,
)


@dataclass(frozen=True)
class ApiExecutionPreflight:
    source_cases_path: str
    source_cases_sha256: str
    source_publication_id: str
    source_history_path: str
    cases: list[ApiTestCase]
    service: str
    structural_sha256: str
    policy_sha256: str
    runtime_values: dict[str, str]
    authentication: ApiAuthentication | None
    trusted_origins: list[str]
    isolation: ApiIsolationPolicy
    operation_policies: dict[str, ApiOperationPolicy]


class FilesystemApiAutomationService:
    def __init__(self, store: FilesystemStore, local_config: FilesystemLocalConfigLoader) -> None:
        self._store = store
        self._local_config = local_config
        self._published_sources = PublishedApiSourceResolver(store)

    def runtime_project(self, workspace: str, environment: str) -> ResolvedApiProject:
        project, binding = self._configured_project(workspace, environment)
        if binding.get("structural_sha256") != project.structural_sha256:
            raise PermissionError(
                "API safety policy changed after prepare; rerun prepare and Review Gate"
            )
        execution = self._store.workspace_config(workspace).get("execution") or {}
        environments = execution.get("environments") if isinstance(execution, dict) else None
        raw_policy = environments.get(environment) if isinstance(environments, dict) else None
        if (
            raw_policy is None
            or project.policy.model_dump(mode="json", exclude_none=True) != raw_policy
        ):
            raise PermissionError(
                "workspace API policy differs from local configuration; "
                "rerun prepare and Review Gate"
            )
        return project

    def recovery_runtime_project(self, workspace: str, environment: str) -> ResolvedApiProject:
        project, _binding = self._configured_project(workspace, environment)
        return project

    def _configured_project(
        self, workspace: str, environment: str
    ) -> tuple[ResolvedApiProject, dict[str, object]]:
        payload = self._store.workspace_config(workspace)
        binding = payload.get("api_project")
        if not isinstance(binding, dict):
            raise PermissionError("workspace is not bound to a configured API project")
        if binding.get("environment") != environment:
            raise PermissionError("requested environment differs from the reviewed API project")
        service = str(binding.get("service") or "")
        config = self._local_config.load_required()
        project = self._local_config.resolve_api_project(config, service, environment)
        return project, binding

    def cleanup_journal_key(self) -> str:
        return self._local_config.load_required().runtime.cleanup_journal_key

    def execute_cleanup_obligation(
        self,
        *,
        workspace: str,
        environment: str,
        execution_id: str,
        obligation: dict[str, object],
        project: ResolvedApiProject | None = None,
    ):
        project = project or self.runtime_project(workspace, environment)
        profile = ExecutionProfile(
            environment=environment,
            base_url_env=project.policy.base_url_env,
            allowed_http_methods=project.policy.allowed_http_methods,
            allow_ui_mutations=False,
            request_timeout_seconds=project.policy.max_request_timeout_seconds,
        )
        policy = self._store.validate_execution_profile(workspace, profile)
        step = ApiCleanupStep.model_validate(obligation["step"])
        runtime_variables = dict(obligation.get("runtime_variables") or {})
        synthetic = ApiTestCase.model_validate(
            {
                "id": "cleanup-recovery-"
                + hashlib.sha256(str(obligation["obligation_id"]).encode()).hexdigest()[:16],
                "title": str(obligation.get("title") or "recovered cleanup"),
                "priority": "P0",
                "contract_status": "confirmed",
                "business_rule_refs": ["RECOVERED-CLEANUP"],
                "review_status": "needs_human_review",
                "review_questions": ["Recovered from the approved cleanup journal"],
                "source_refs": [
                    {
                        "source_type": "openapi",
                        "source_path": "published/api_test_draft/current.yml",
                        "chunk_id": "cleanup-recovery",
                        "locator": f"{step.request.method} {step.request.path}",
                        "summary": "Approved cleanup request recovered after interruption",
                        "confidence": "high",
                    }
                ],
                "pending": [],
                "request": step.request.model_dump(mode="json"),
                "assertions": [item.model_dump(mode="json") for item in step.assertions],
                "variables": (
                    {
                        "datasets": [{"id": "recovery", "values": runtime_variables}],
                        "extract": {},
                    }
                    if runtime_variables
                    else {"datasets": [], "extract": {}}
                ),
                "cleanup": [],
            }
        )
        evidence = execute_api_cases(
            [synthetic],
            run_id=f"{obligation['obligation_id']}::recovery",
            source_cases_path="published/api_test_draft/current.yml",
            profile=profile,
            env=project.runtime_values,
            authentication=policy.api_auth if policy is not None else None,
            trusted_origins=policy.trusted_origins if policy is not None else None,
            isolation=project.policy.isolation,
            operation_policies=project.policy.operation_policies,
            execution_identity=execution_id,
        )
        return evidence.cases[0]

    def published_sha256(self, workspace: str) -> str:
        _root, _target, _draft, digest = self._published_cases(
            workspace,
            "published/api_test_draft/current.yml",
        )
        return digest

    def published_report_source(
        self,
        workspace: str,
        *,
        source_publication_id: str | None,
        source_history_path: str | None,
        source_cases_sha256: str,
    ) -> tuple[list[ApiTestCase], str, str]:
        """Read immutable published cases without applying today's runtime policy.

        Historical report generation is a read-only projection of stored Evidence. It
        must remain available when local credentials or reviewed safety policy have
        changed, and therefore deliberately does not construct an execution profile.
        """
        source = self.validate_historical_source(
            workspace,
            source_publication_id=source_publication_id,
            source_history_path=source_history_path,
            source_cases_sha256=source_cases_sha256,
        )
        draft = ApiTestCasesDraft.model_validate(yaml.safe_load(source.content.decode("utf-8")))
        payload = self._store.workspace_config(workspace)
        binding = payload.get("api_project")
        service = binding.get("service") if isinstance(binding, dict) else None
        if not isinstance(service, str) or not service:
            raise PermissionError("workspace is not bound to an API service")
        return list(draft.cases), service, source.content_sha256

    def validate_historical_source(
        self,
        workspace: str,
        *,
        source_publication_id: str | None,
        source_history_path: str | None,
        source_cases_sha256: str,
    ):
        return self._published_sources.resolve_historical(
            workspace,
            publication_id=source_publication_id,
            history_path=source_history_path,
            expected_sha256=source_cases_sha256,
        )

    def execution_profile(self, workspace: str, environment: str) -> ExecutionProfile:
        project = self.runtime_project(workspace, environment)
        return ExecutionProfile(
            environment=environment,
            base_url_env=project.policy.base_url_env,
            allowed_http_methods=project.policy.allowed_http_methods,
            allow_ui_mutations=False,
            request_timeout_seconds=project.policy.max_request_timeout_seconds,
        )

    def _published_cases(
        self, workspace: str, relative_path: str
    ) -> tuple[Path, Path, ApiTestCasesDraft, str]:
        root = self._store.require_workspace(workspace).resolve()
        target = (root / relative_path).resolve()
        published = (root / "published").resolve()
        if not target.is_file() or published not in target.parents:
            raise ValueError("API automation only accepts published API cases")
        raw = target.read_bytes()
        payload = yaml.safe_load(raw.decode("utf-8"))
        draft = ApiTestCasesDraft.model_validate(payload)
        return root, target, draft, hashlib.sha256(raw).hexdigest()

    def execute(self, command: ExecuteApiCasesCommand) -> ExecutionEvidence:
        return self.execute_observed(command)

    def execute_observed(
        self,
        command: ExecuteApiCasesCommand,
        event_callback=None,
    ) -> ExecutionEvidence:
        root, target, draft, source_sha256 = self._published_cases(
            command.workspace_id, command.cases_path
        )
        if command.source_cases_sha256 is not None and source_sha256 != command.source_cases_sha256:
            raise ValueError("published API cases hash does not match exported pytest adapter")
        policy = self._store.validate_execution_profile(
            command.workspace_id, command.execution_profile
        )
        project = self.runtime_project(command.workspace_id, command.execution_profile.environment)
        validate_api_cleanup_policy(
            draft.cases,
            project.policy.cleanup_exempt_operations,
            project.policy.operation_policies,
        )
        return execute_api_cases(
            draft.cases,
            run_id=command.run_id,
            source_cases_path=target.relative_to(root).as_posix(),
            profile=command.execution_profile,
            env=project.runtime_values,
            authentication=policy.api_auth if policy is not None else None,
            trusted_origins=policy.trusted_origins if policy is not None else None,
            isolation=project.policy.isolation,
            operation_policies=project.policy.operation_policies,
            event_callback=event_callback,
        )

    def execute_preflight(
        self,
        command: ExecuteApiCasesCommand,
        preflight: ApiExecutionPreflight,
        event_callback=None,
    ) -> ExecutionEvidence:
        """Execute the exact parsed cases and runtime view frozen by preflight."""
        if command.source_cases_sha256 != preflight.source_cases_sha256:
            raise ValueError("execution command does not match the frozen API preflight")
        return execute_api_cases(
            preflight.cases,
            run_id=command.run_id,
            source_cases_path=preflight.source_cases_path,
            profile=command.execution_profile,
            env=preflight.runtime_values,
            authentication=preflight.authentication,
            trusted_origins=preflight.trusted_origins,
            isolation=preflight.isolation,
            operation_policies=preflight.operation_policies,
            event_callback=event_callback,
        )

    def preflight(self, command: ExecuteApiCasesCommand) -> ApiExecutionPreflight:
        source = self._published_sources.resolve_current(command.workspace_id)
        draft = ApiTestCasesDraft.model_validate(yaml.safe_load(source.content.decode("utf-8")))
        source_sha256 = source.content_sha256
        if command.source_cases_sha256 is not None and source_sha256 != command.source_cases_sha256:
            raise ValueError("published API cases hash changed before execution")
        policy = self._store.validate_execution_profile(
            command.workspace_id, command.execution_profile
        )
        project = self.runtime_project(command.workspace_id, command.execution_profile.environment)
        validate_api_cleanup_policy(
            draft.cases,
            project.policy.cleanup_exempt_operations,
            project.policy.operation_policies,
        )
        validate_api_execution_preflight(
            draft.cases,
            profile=command.execution_profile,
            env=project.runtime_values,
            authentication=policy.api_auth if policy is not None else None,
            trusted_origins=policy.trusted_origins if policy is not None else None,
            isolation=project.policy.isolation,
            operation_policies=project.policy.operation_policies,
        )
        return ApiExecutionPreflight(
            source_cases_path=source.workspace_relative_path,
            source_cases_sha256=source_sha256,
            source_publication_id=source.publication_id,
            source_history_path=source.workspace_relative_path,
            cases=list(draft.cases),
            service=project.service,
            structural_sha256=project.structural_sha256,
            policy_sha256=project.policy_sha256,
            runtime_values=dict(project.runtime_values),
            authentication=policy.api_auth if policy is not None else None,
            trusted_origins=list(policy.trusted_origins) if policy is not None else [],
            isolation=project.policy.isolation,
            operation_policies=dict(project.policy.operation_policies),
        )

    def export_pytest(self, command: ExportApiPytestCommand) -> ApiPytestExportResult:
        root, source, draft, source_sha256 = self._published_cases(
            command.workspace_id, command.cases_path
        )
        validate_api_case_runtime_definitions(draft.cases)
        target = (root / command.output_path).resolve()
        exports = (root / "exports").resolve()
        if target.suffix != ".py" or exports not in target.parents:
            raise ValueError("pytest export path must be a .py file below workspace exports/")
        if target.exists() and not command.overwrite:
            raise FileExistsError(f"pytest export already exists: {command.output_path}")
        payload = self._store.workspace_config(command.workspace_id)
        binding = payload.get("api_project")
        if not isinstance(binding, dict) or not isinstance(binding.get("environment"), str):
            raise PermissionError("workspace is not bound to an API environment")
        content = render_pytest_adapter(
            workspace_id=command.workspace_id,
            cases_path=source.relative_to(root).as_posix(),
            source_sha256=source_sha256,
            base_url_env=draft.base_url_env,
            evidence_case_ids=api_execution_case_ids(draft.cases),
            environment=binding["environment"],
        )
        atomic_text(target, content)
        return ApiPytestExportResult(
            workspace_id=command.workspace_id,
            source_cases_path=source.relative_to(root).as_posix(),
            source_cases_sha256=source_sha256,
            output_path=target.relative_to(root).as_posix(),
            output_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )


def render_pytest_adapter(
    *,
    workspace_id: str,
    cases_path: str,
    source_sha256: str,
    base_url_env: str,
    evidence_case_ids: list[str],
    environment: str,
) -> str:
    values = {
        "workspace_id": json.dumps(workspace_id, ensure_ascii=False),
        "cases_path": json.dumps(cases_path, ensure_ascii=False),
        "source_sha256": json.dumps(source_sha256),
        "base_url_env": json.dumps(base_url_env),
        "evidence_case_ids": json.dumps(evidence_case_ids, ensure_ascii=False),
        "environment": json.dumps(environment, ensure_ascii=False),
    }
    return f"""# Generated deterministically by Agentic-QA. Do not add credentials here.
from __future__ import annotations

from pathlib import Path

import pytest

from harness import ExecuteApiCasesCommand, ExecutionProfile, Harness

WORKSPACE_ID = {values["workspace_id"]}
CASES_PATH = {values["cases_path"]}
SOURCE_CASES_SHA256 = {values["source_sha256"]}
BASE_URL_ENV = {values["base_url_env"]}
EXPECTED_CASE_IDS = {values["evidence_case_ids"]}
ENVIRONMENT = {values["environment"]}


@pytest.fixture(scope="session")
def _api_execution_results() -> dict[str, object]:
    harness = Harness(Path(__file__).resolve().parents[4])
    profile = harness.api_execution_profile(WORKSPACE_ID, ENVIRONMENT)
    evidence = harness.execute_api_cases(
        ExecuteApiCasesCommand(
            workspace_id=WORKSPACE_ID,
            run_id="pytest-api-export",
            cases_path=CASES_PATH,
            source_cases_sha256=SOURCE_CASES_SHA256,
            execution_profile=profile,
        )
    )
    results = {{case.case_id: case for case in evidence.cases}}
    assert list(results) == EXPECTED_CASE_IDS, (
        f"API execution evidence ids changed: expected={{EXPECTED_CASE_IDS}}, "
        f"actual={{list(results)}}"
    )
    return results


@pytest.mark.parametrize("case_id", EXPECTED_CASE_IDS, ids=EXPECTED_CASE_IDS)
def test_published_api_case(
    _api_execution_results: dict[str, object],
    case_id: str,
) -> None:
    result = _api_execution_results[case_id]
    assert result.status == "passed", (
        f"API case {{case_id}} finished with {{result.status}}: {{result.error}}"
    )
"""
