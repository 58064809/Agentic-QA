from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime_mvp_fixtures import create_mvp_repo  # noqa: E402

from runtime.cli.importer import _import_network_capture_to_workspace  # noqa: E402
from runtime.cli.parser import (  # noqa: E402
    _extract_network_capture_path,
    _extract_prd_workspace_path,
)
from runtime.graph.app import (  # noqa: E402
    resume_recorded_workflow,
    run_api_discovery_report_workflow,
)
from runtime.graph.nodes.api_discovery import api_discovery_quality_check_node  # noqa: E402
from runtime.graph.state import QAWorkflowState  # noqa: E402
from runtime.llm.config import OpenAICompatibleConfig  # noqa: E402
from runtime.llm.intent_router import route_intent  # noqa: E402
from runtime.workspace import ARTIFACT_SPECS  # noqa: E402


def add_discovery_context_files(repo_root: Path) -> None:
    files = {
        "docs/api-discovery.md": (REPO_ROOT / "docs/api-discovery.md").read_text(encoding="utf-8"),
        "prompts/api-discovery.md": (REPO_ROOT / "prompts/api-discovery.md").read_text(
            encoding="utf-8"
        ),
        "skills/api-discovery.md": (REPO_ROOT / "skills/api-discovery.md").read_text(
            encoding="utf-8"
        ),
        "workflows/runtime/api-discovery-report.workflow.yml": (
            REPO_ROOT / "workflows/runtime/api-discovery-report.workflow.yml"
        ).read_text(encoding="utf-8"),
    }
    for relative_path, content in files.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def write_capture(repo_root: Path) -> None:
    capture = {
        "calls": [
            {
                "method": "POST",
                "url": "https://example.test/api/activity/join",
                "status": 200,
                "request_body": {"activityId": "A1", "token": "secret-token"},
                "response_body": {"code": 0, "data": {"status": "joined"}},
            }
        ]
    }
    path = repo_root / "prd/demo-requirement/input/network-capture.json"
    path.write_text(json.dumps(capture), encoding="utf-8")


def test_api_discovery_artifact_spec_is_registered():
    spec = ARTIFACT_SPECS["api_discovery_report"]

    assert spec["current_path"] == "artifacts/api-discovery-report.md"
    assert spec["review_path"] == "reviews/api-discovery-report.review.yml"


def test_intent_routes_api_discovery_without_llm(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    route = route_intent(
        "基于 prd/demo-requirement/input/network-capture.har 生成接口发现报告",
        OpenAICompatibleConfig.from_env(),
    )

    assert route.intent == "api_discovery_report"
    assert route.prd_path == "prd/demo-requirement"


def test_network_capture_path_parser_derives_prd_workspace():
    command = "基于 prd/demo/input/network-capture.har 生成接口发现报告"

    assert _extract_network_capture_path(command) == "prd/demo/input/network-capture.har"
    assert _extract_prd_workspace_path(command) == "prd/demo"


def test_external_network_capture_is_copied_to_standard_workspace_path(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    external = tmp_path / "captures" / "activity.har"
    external.parent.mkdir()
    external.write_text('{"log":{"entries":[]}}', encoding="utf-8")

    target = _import_network_capture_to_workspace(
        repo_root,
        "prd/demo-requirement",
        str(external),
    )

    assert target == repo_root / "prd/demo-requirement/input/network-capture.har"
    assert target.read_text(encoding="utf-8") == external.read_text(encoding="utf-8")


def test_api_discovery_report_generates_preview_and_sanitizes(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_discovery_context_files(repo_root)
    write_capture(repo_root)

    result = run_api_discovery_report_workflow(
        "基于抓包生成接口发现报告",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )

    assert result.success
    preview = repo_root / result.output_paths["api_discovery_report"]
    assert preview.is_file()
    content = preview.read_text(encoding="utf-8")
    assert "/api/activity/join" in content
    assert "secret-token" not in content
    assert not (repo_root / "prd/demo-requirement/artifacts/api-discovery-report.md").exists()


def test_api_discovery_promote_writes_formal_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_discovery_context_files(repo_root)
    write_capture(repo_root)

    result = run_api_discovery_report_workflow(
        "基于抓包生成接口发现报告",
        "prd/demo-requirement",
        repo_root=repo_root,
    )
    resumed = resume_recorded_workflow(
        result.run_id or "",
        action="approve",
        user_input="接口发现报告通过",
        target_artifact="api_discovery_report",
        repo_root=repo_root,
    )
    assert resumed.success
    assert resumed.review_status == "confirmed"
    assert "artifact_promoter" in resumed.executed_nodes
    formal = repo_root / "prd/demo-requirement/artifacts/api-discovery-report.md"
    assert formal.is_file()
    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/api-discovery-report.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["status"] == "confirmed"


def test_api_discovery_quality_rejects_unsanitized_secret(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    state = QAWorkflowState(
        user_input="接口发现报告",
        prd_path="prd/demo-requirement",
        task_type="api_discovery_report",
        run_id="run-1",
        draft_artifacts={
            "api_discovery_report": (
                "# 接口发现报告\n\n" "## 1. 采集来源\n\n" "Authorization: Bearer abcdefghijklmnop"
            )
        },
        output_paths={
            "api_discovery_report": "prd/demo-requirement/runs/run-1/artifact-preview.md"
        },
    )

    checked = api_discovery_quality_check_node(state, repo_root)

    assert any("未脱敏" in error for error in checked.quality_errors)
