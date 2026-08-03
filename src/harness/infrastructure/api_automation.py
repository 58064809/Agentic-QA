from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import yaml

from harness.domain.models import (
    ApiPytestExportResult,
    ExecuteApiCasesCommand,
    ExportApiPytestCommand,
)
from harness.domain.schemas.api_test_cases import (
    ApiTestCasesDraft,
    api_execution_case_ids,
    validate_api_case_runtime_definitions,
)
from harness.domain.schemas.execution_evidence import ExecutionEvidence
from harness.infrastructure.persistence.common import atomic_text
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.tools.api_execution import execute_api_cases


class FilesystemApiAutomationService:
    def __init__(self, store: FilesystemStore) -> None:
        self._store = store

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
        root, target, draft, source_sha256 = self._published_cases(
            command.workspace_id, command.cases_path
        )
        if command.source_cases_sha256 is not None and source_sha256 != command.source_cases_sha256:
            raise ValueError("published API cases hash does not match exported pytest adapter")
        policy = self._store.validate_execution_profile(
            command.workspace_id, command.execution_profile
        )
        return execute_api_cases(
            draft.cases,
            run_id=command.run_id,
            source_cases_path=target.relative_to(root).as_posix(),
            profile=command.execution_profile,
            env=os.environ,
            authentication=policy.api_auth if policy is not None else None,
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
        content = render_pytest_adapter(
            workspace_id=command.workspace_id,
            cases_path=source.relative_to(root).as_posix(),
            source_sha256=source_sha256,
            base_url_env=draft.base_url_env,
            evidence_case_ids=api_execution_case_ids(draft.cases),
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
) -> str:
    values = {
        "workspace_id": json.dumps(workspace_id, ensure_ascii=False),
        "cases_path": json.dumps(cases_path, ensure_ascii=False),
        "source_sha256": json.dumps(source_sha256),
        "base_url_env": json.dumps(base_url_env),
        "evidence_case_ids": json.dumps(evidence_case_ids, ensure_ascii=False),
    }
    return f"""# Generated deterministically by Agentic-QA. Do not add credentials here.
from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness import ExecuteApiCasesCommand, ExecutionProfile, Harness

WORKSPACE_ID = {values["workspace_id"]}
CASES_PATH = {values["cases_path"]}
SOURCE_CASES_SHA256 = {values["source_sha256"]}
BASE_URL_ENV = {values["base_url_env"]}
EXPECTED_CASE_IDS = {values["evidence_case_ids"]}


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{{name}} must be configured explicitly")
    return value


@pytest.fixture(scope="session")
def _api_execution_results() -> dict[str, object]:
    environment = _required_environment("AGENTIC_QA_EXECUTION_ENVIRONMENT")
    methods = [
        item.strip().upper()
        for item in _required_environment("AGENTIC_QA_ALLOWED_HTTP_METHODS").split(",")
        if item.strip()
    ]
    profile = ExecutionProfile(
        environment=environment,
        base_url_env=BASE_URL_ENV,
        allowed_http_methods=methods,
        request_timeout_seconds=int(os.environ.get("AGENTIC_QA_REQUEST_TIMEOUT_SECONDS", "10")),
    )
    evidence = Harness(Path(os.environ.get("AGENTIC_QA_REPO_ROOT", "."))).execute_api_cases(
        ExecuteApiCasesCommand(
            workspace_id=os.environ.get("AGENTIC_QA_WORKSPACE", WORKSPACE_ID),
            run_id=os.environ.get("AGENTIC_QA_RUN_ID", "pytest-api-export"),
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
