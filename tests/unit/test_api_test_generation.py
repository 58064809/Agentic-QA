from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime_mvp_fixtures import create_mvp_repo  # noqa: E402

from runtime.graph.app import (  # noqa: E402
    promote_artifacts,
    resume_recorded_workflow,
    run_api_test_draft_workflow,
)
from runtime.graph.nodes.api_test_generation import api_test_quality_check_node  # noqa: E402
from runtime.graph.state import QAWorkflowState  # noqa: E402
from runtime.llm.config import OpenAICompatibleConfig  # noqa: E402
from runtime.llm.intent_router import route_intent  # noqa: E402
from runtime.workspace import ARTIFACT_SPECS  # noqa: E402


def add_api_test_context_files(repo_root: Path) -> None:
    files = {
        "docs/api-test-generation.md": (REPO_ROOT / "docs/api-test-generation.md").read_text(
            encoding="utf-8"
        ),
        "prompts/api-test-generation.md": (REPO_ROOT / "prompts/api-test-generation.md").read_text(
            encoding="utf-8"
        ),
        "skills/api-testing.md": (REPO_ROOT / "skills/api-testing.md").read_text(encoding="utf-8"),
        "workflows/runtime/api-test-draft.workflow.yml": (
            REPO_ROOT / "workflows/runtime/api-test-draft.workflow.yml"
        ).read_text(encoding="utf-8"),
    }
    for relative_path, content in files.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_api_test_draft_with_api_doc_generates_candidate_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_api_test_context_files(repo_root)

    result = run_api_test_draft_workflow(
        "基于 prd/demo-requirement 生成接口测试草稿",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
        use_llm=False,
    )

    assert result.success
    assert result.task_type == "api_test_draft"
    assert result.review_status == "needs_human_review"
    assert "api_test_draft" in result.draft_artifacts
    draft = result.draft_artifacts["api_test_draft"]
    assert "POST" in draft
    assert "/api/v1/auth/login" in draft
    assert "pytest + requests 脚本草稿" in draft
    assert not (repo_root / "prd/demo-requirement/artifacts/api-test-draft.md").exists()


def test_api_test_draft_without_api_doc_marks_missing_contract(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_api_test_context_files(repo_root)
    (repo_root / "prd/demo-requirement/input/api.md").unlink()

    result = run_api_test_draft_workflow(
        "生成接口测试草稿",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
        use_llm=False,
    )

    assert result.success
    draft = result.draft_artifacts["api_test_draft"]
    assert "待补充接口文档" in draft
    assert "待确认 URL" in draft
    assert "待确认 Method" in draft


def test_api_test_draft_uses_discovery_json_when_api_doc_missing(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_api_test_context_files(repo_root)
    (repo_root / "prd/demo-requirement/input/api.md").unlink()
    discovery_dir = repo_root / "prd/demo-requirement/runs/run-discovery"
    discovery_dir.mkdir(parents=True)
    discovery_payload = {
        "source_path": "prd/demo-requirement/input/network-capture.json",
        "candidates": [
            {
                "method": "POST",
                "path": "/api/activity/join",
                "call_count": 1,
                "status_codes": [200],
                "request_schema": {"activityId": "string"},
                "response_schema": {"code": "number", "data": {"status": "string"}},
            }
        ],
    }
    (discovery_dir / "api_discovery_report.discovery.json").write_text(
        json.dumps(discovery_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    result = run_api_test_draft_workflow(
        "生成接口测试草稿",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
        use_llm=False,
    )

    assert result.success
    draft = result.draft_artifacts["api_test_draft"]
    assert "/api/activity/join" in draft
    assert "Playwright network capture / api-discovery-report" in draft
    assert "需与 Swagger / Apifox 契约核对" in draft
    assert "待补充接口文档" in draft


def test_api_test_draft_approve_write_only_writes_run_preview(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_api_test_context_files(repo_root)

    result = run_api_test_draft_workflow(
        "生成 pytest requests 接口测试",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
        use_llm=False,
    )

    assert result.success
    assert result.wrote_file
    preview = repo_root / result.output_paths["api_test_draft"]
    assert preview.is_file()
    assert preview.as_posix().endswith(
        f"/prd/demo-requirement/runs/{result.run_id}/artifact-preview.md"
    )
    assert not (repo_root / "prd/demo-requirement/artifacts/api-test-draft.md").exists()


def test_api_test_draft_promote_writes_formal_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_api_test_context_files(repo_root)

    result = run_api_test_draft_workflow(
        "生成接口测试草稿",
        "prd/demo-requirement",
        repo_root=repo_root,
        use_llm=False,
    )
    resumed = resume_recorded_workflow(
        result.run_id or "",
        action="approve",
        user_input="接口测试草稿通过",
        target_artifact="api_test_draft",
        repo_root=repo_root,
    )
    promoted = promote_artifacts(
        "prd/demo-requirement",
        result.run_id or "",
        repo_root=repo_root,
        task_type="api_test_draft",
    )

    assert resumed.success
    assert promoted.success
    formal = repo_root / "prd/demo-requirement/artifacts/api-test-draft.md"
    assert formal.is_file()
    assert "status: confirmed" in formal.read_text(encoding="utf-8")
    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/api-test-draft.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["status"] == "confirmed"


def test_api_test_draft_artifact_spec_is_registered():
    spec = ARTIFACT_SPECS["api_test_draft"]

    assert spec["current_path"] == "artifacts/api-test-draft.md"
    assert spec["review_path"] == "reviews/api-test-draft.review.yml"


def test_intent_routes_api_test_draft_without_llm(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    route = route_intent(
        "基于 prd/demo-requirement 生成接口测试草稿",
        OpenAICompatibleConfig.from_env(),
    )

    assert route.is_valid
    assert route.intent == "api_test_draft"
    assert route.prd_path == "prd/demo-requirement"


def test_api_test_quality_rejects_missing_sections_and_execution_claims(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    state = QAWorkflowState(
        user_input="生成接口测试草稿",
        prd_path="prd/demo-requirement",
        task_type="api_test_draft",
        run_id="run-1",
        draft_artifacts={
            "api_test_draft": "# 接口测试草稿\n\n## 1. 接口清单\n\n已执行，执行通过。\n"
        },
        output_paths={"api_test_draft": "prd/demo-requirement/runs/run-1/artifact-preview.md"},
        loaded_files={},
    )

    checked = api_test_quality_check_node(state, repo_root)

    assert any("缺少章节: 断言策略" in error for error in checked.quality_errors)
    assert any("待补充接口文档" in error for error in checked.quality_errors)
    assert any("执行结论" in error for error in checked.quality_errors)
