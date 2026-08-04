from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from harness import (
    CreateWorkspaceCommand,
    ExecuteApiCasesCommand,
    ExecutionProfile,
    ExportApiPytestCommand,
    Harness,
)
from harness.infrastructure.workflow.engine import default_recorded_api_test_cases


def _publish_cases(repo_root: Path, workspace: str) -> Path:
    harness = Harness(repo_root)
    workspace_root = harness.create_workspace(CreateWorkspaceCommand(workspace_id=workspace))
    draft = default_recorded_api_test_cases("export API cases")
    target = workspace_root / "published" / "api_test_draft" / "current.yml"
    target.parent.mkdir(parents=True)
    target.write_text(
        yaml.safe_dump(draft.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return target


def test_pytest_export_is_deterministic_and_bound_to_published_hash(tmp_path: Path) -> None:
    source = _publish_cases(tmp_path, "demo")
    harness = Harness(tmp_path)
    command = ExportApiPytestCommand(workspace_id="demo")

    first = harness.export_api_pytest(command)
    output = tmp_path / "workspaces" / "demo" / first.output_path
    content = output.read_text(encoding="utf-8")
    assert first.source_cases_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert first.output_sha256 == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert "ExecuteApiCasesCommand" in content
    assert first.source_cases_sha256 in content
    assert "AGENTIC_QA_EXECUTION_ENVIRONMENT" in content
    assert '@pytest.mark.parametrize("case_id", EXPECTED_CASE_IDS' in content
    assert "def test_published_api_case(" in content
    assert "def test_published_api_scenario" not in content
    compile(content, str(output), "exec")

    with pytest.raises(FileExistsError):
        harness.export_api_pytest(command)
    second = harness.export_api_pytest(command.model_copy(update={"overwrite": True}))
    assert second == first


def test_pytest_export_rejects_non_published_source_and_outside_target(tmp_path: Path) -> None:
    _publish_cases(tmp_path, "demo")
    harness = Harness(tmp_path)

    with pytest.raises(ValueError, match="published"):
        harness.export_api_pytest(
            ExportApiPytestCommand(workspace_id="demo", cases_path="sources/openapi.yml")
        )
    with pytest.raises(ValueError, match="exports"):
        harness.export_api_pytest(
            ExportApiPytestCommand(workspace_id="demo", output_path="published/test_api.py")
        )


def test_public_api_execution_rejects_export_hash_drift_before_request(tmp_path: Path) -> None:
    _publish_cases(tmp_path, "demo")
    workspace_config = tmp_path / "workspaces" / "demo" / "workspace.yml"
    config = yaml.safe_load(workspace_config.read_text(encoding="utf-8"))
    config["execution"]["environments"]["qa"] = {
        "base_url_env": "AGENTIC_QA_BASE_URL",
        "trusted_origins": ["https://qa.example.test"],
        "allowed_http_methods": ["GET"],
    }
    workspace_config.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="hash"):
        Harness(tmp_path).execute_api_cases(
            ExecuteApiCasesCommand(
                workspace_id="demo",
                run_id="pytest-api",
                source_cases_sha256="0" * 64,
                execution_profile=ExecutionProfile(
                    environment="qa",
                    base_url_env="AGENTIC_QA_BASE_URL",
                    allowed_http_methods=["GET"],
                ),
            )
        )


def test_public_api_execution_enforces_workspace_trusted_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _publish_cases(tmp_path, "demo")
    workspace_config = tmp_path / "workspaces" / "demo" / "workspace.yml"
    config = yaml.safe_load(workspace_config.read_text(encoding="utf-8"))
    config["execution"]["environments"]["qa"] = {
        "base_url_env": "AGENTIC_QA_BASE_URL",
        "trusted_origins": ["https://qa.example.test"],
        "allowed_http_methods": ["GET"],
    }
    workspace_config.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("AGENTIC_QA_BASE_URL", "https://outside.example.test")

    with pytest.raises(ValueError, match="not trusted"):
        Harness(tmp_path).execute_api_cases(
            ExecuteApiCasesCommand(
                workspace_id="demo",
                run_id="untrusted-origin",
                execution_profile=ExecutionProfile(
                    environment="qa",
                    base_url_env="AGENTIC_QA_BASE_URL",
                    allowed_http_methods=["GET"],
                ),
            )
        )


def test_api_cases_schema_version_remains_v1_1() -> None:
    assert default_recorded_api_test_cases("schema check").schema_version == (
        "agentic-qa.api-cases.v1.1"
    )
