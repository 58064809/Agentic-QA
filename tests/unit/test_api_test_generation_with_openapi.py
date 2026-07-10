from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime_mvp_fixtures import create_mvp_repo  # noqa: E402
from test_api_test_generation import add_api_test_context_files  # noqa: E402

from runtime.cli.parser import _extract_api_doc_path  # noqa: E402
from runtime.cli.promoter import _run_workflow  # noqa: E402
from runtime.graph.app import run_api_test_draft_workflow  # noqa: E402
from runtime.graph.nodes.api_test_generation import render_api_test_cases_yaml  # noqa: E402
from runtime.graph.state import QAWorkflowState  # noqa: E402
from runtime.llm.config import OpenAICompatibleConfig  # noqa: E402
from runtime.llm.intent_router import route_intent  # noqa: E402


def openapi_with_security() -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Activity API", "version": "1"},
        "components": {"securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}}},
        "security": [{"BearerAuth": []}],
        "paths": {
            "/api/activity/join": {
                "post": {
                    "summary": "参加活动",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["activityId"],
                                    "properties": {
                                        "activityId": {"type": "string"},
                                        "score": {"type": "integer"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "ok"}, "401": {"description": "bad"}},
                }
            }
        },
    }


def test_api_test_draft_uses_workspace_openapi_normalized_api_doc(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_api_test_context_files(repo_root)
    source = repo_root / "prd/demo-requirement/input/api.openapi.json"
    source.write_text(json.dumps(openapi_with_security()), encoding="utf-8")
    (repo_root / "prd/demo-requirement/input/api.md").unlink()

    result = run_api_test_draft_workflow(
        "生成接口测试草稿",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
        use_llm=False,
    )

    assert result.success
    api_md = repo_root / "prd/demo-requirement/input/api.md"
    assert "## POST /api/activity/join" in api_md.read_text(encoding="utf-8")
    draft = result.draft_artifacts["api_test_draft"]
    assert "/api/activity/join" in draft
    assert "必填字段缺失" in draft
    assert "未登录或鉴权失败" in draft
    state = QAWorkflowState(
        prd_path="prd/demo-requirement",
        loaded_files={
            "prd/demo-requirement/input/api.md": api_md.read_text(encoding="utf-8"),
            "prd/demo-requirement/input/requirement.md": "用户参加活动。",
        },
    )
    payload = yaml.safe_load(render_api_test_cases_yaml(state, repo_root))
    case = payload["cases"][0]
    assert case["contract_status"] == "confirmed"
    assert case["request"]["method"] == "POST"
    assert case["request"]["path"] == "/api/activity/join"
    assert {"type": "status_code", "expected": [200]} in case["assertions"]


def test_cli_workflow_imports_external_openapi_before_api_test_draft(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_api_test_context_files(repo_root)
    external = tmp_path / "activity-openapi.json"
    external.write_text(json.dumps(openapi_with_security()), encoding="utf-8")

    result = _run_workflow(
        "基于 openapi.json 生成接口测试草稿",
        "prd/demo-requirement",
        intent="api_test_draft",
        repo_root=repo_root,
        api_doc_path=str(external),
        debug=True,
    )

    assert result.success
    copied = repo_root / "prd/demo-requirement/input/api.openapi.json"
    assert copied.is_file()
    assert "## POST /api/activity/join" in (
        repo_root / "prd/demo-requirement/input/api.md"
    ).read_text(encoding="utf-8")
    assert "/api/activity/join" in result.draft_artifacts["api_test_draft"]


def test_cli_and_intent_split_api_doc_path_from_prd_path(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    user_input = r"基于 D:\api\activity-openapi.json 生成接口测试草稿，PRD 是 prd/5月活动玩法"

    route = route_intent(user_input, OpenAICompatibleConfig.from_env())

    assert route.intent == "api_test_draft"
    assert route.prd_path == "prd/5月活动玩法"
    assert _extract_api_doc_path(user_input) == r"D:\api\activity-openapi.json"
