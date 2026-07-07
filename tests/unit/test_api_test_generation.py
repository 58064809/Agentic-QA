from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime_mvp_fixtures import create_mvp_repo  # noqa: E402

from runtime.graph.app import (  # noqa: E402
    resume_recorded_workflow,
    run_api_test_draft_workflow,
    run_rag_automation_case_workflow,
)
from runtime.graph.nodes.api_test_generation import (  # noqa: E402
    API_CASES_FORMAL_PATH,
    API_CASES_YAML_DEBUG_KEY,
    API_CASES_YAML_FILENAME,
    API_RAG_RUN_RECORD_FILENAME,
    api_test_quality_check_node,
)
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
        "workflows/runtime/rag-automation-case.workflow.yml": (
            REPO_ROOT / "workflows/runtime/rag-automation-case.workflow.yml"
        ).read_text(encoding="utf-8"),
        "docs/automation-case-generation.md": (
            REPO_ROOT / "docs/automation-case-generation.md"
        ).read_text(encoding="utf-8"),
        "docs/rag-architecture.md": (REPO_ROOT / "docs/rag-architecture.md").read_text(
            encoding="utf-8"
        ),
        "docs/rag-run-record-spec.md": (REPO_ROOT / "docs/rag-run-record-spec.md").read_text(
            encoding="utf-8"
        ),
        "workflows/10-rag-automation-case-generation-workflow.md": (
            REPO_ROOT / "workflows/10-rag-automation-case-generation-workflow.md"
        ).read_text(encoding="utf-8"),
        "prompts/rag-automation-case-prompt.md": (
            REPO_ROOT / "prompts/rag-automation-case-prompt.md"
        ).read_text(encoding="utf-8"),
        "rules/automation-case-rules.md": (REPO_ROOT / "rules/automation-case-rules.md").read_text(
            encoding="utf-8"
        ),
        "rules/rag-rules.md": (REPO_ROOT / "rules/rag-rules.md").read_text(encoding="utf-8"),
        "rules/source-reference-rules.md": (
            REPO_ROOT / "rules/source-reference-rules.md"
        ).read_text(encoding="utf-8"),
        "knowledge/automation/yaml-case-schema.md": (
            REPO_ROOT / "knowledge/automation/yaml-case-schema.md"
        ).read_text(encoding="utf-8"),
        "knowledge/automation/assertion-rules.md": (
            REPO_ROOT / "knowledge/automation/assertion-rules.md"
        ).read_text(encoding="utf-8"),
        "knowledge/automation/variable-extraction-rules.md": (
            REPO_ROOT / "knowledge/automation/variable-extraction-rules.md"
        ).read_text(encoding="utf-8"),
        "knowledge/templates/rag-run-record-template.json": (
            REPO_ROOT / "knowledge/templates/rag-run-record-template.json"
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
    api_cases = preview.with_name(API_CASES_YAML_FILENAME)
    assert api_cases.is_file()
    payload = yaml.safe_load(api_cases.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "agentic-qa.api-cases.v1"
    assert payload["status"] == "needs_human_review"
    assert payload["human_review_required"] is True
    assert payload["base_url_env"] == "AGENTIC_QA_BASE_URL"
    assert payload["business_rules"]
    assert payload["source_refs"]
    assert payload["cases"]
    assert payload["cases"][0]["path"] == "/api/v1/auth/login"
    assert payload["cases"][0]["business_rule_refs"]
    assert payload["cases"][0]["source_refs"]
    assert payload["cases"][0]["review_status"] == "needs_human_review"
    rag_record = preview.with_name(API_RAG_RUN_RECORD_FILENAME)
    assert rag_record.is_file()
    record = json.loads(rag_record.read_text(encoding="utf-8"))
    assert record["task_type"] == "rag_automation_case_generation"
    assert record["review_gate"]["status"] == "needs_human_review"
    assert record["selected_context"]
    global_record = repo_root / "rag/run_records" / f"{result.run_id}.json"
    assert global_record.is_file()
    latest = yaml.safe_load(
        (repo_root / "prd/demo-requirement/runs/latest.yml").read_text(encoding="utf-8")
    )
    assert latest["sidecar_paths"]["rag_run_record"].endswith(API_RAG_RUN_RECORD_FILENAME)
    assert (
        latest["sidecar_paths"]["rag_run_record_global"]
        == global_record.relative_to(repo_root).as_posix()
    )
    assert not (repo_root / "prd/demo-requirement/artifacts/api-test-draft.md").exists()
    assert not (repo_root / "prd/demo-requirement/artifacts/api-test-cases.yml").exists()


def test_rag_automation_case_workflow_runs_as_stategraph_sidecar(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_api_test_context_files(repo_root)

    result = run_rag_automation_case_workflow(
        "基于 prd/demo-requirement 用 RAG 生成 YAML 接口自动化用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
        use_llm=False,
    )

    assert result.success
    assert result.orchestration == "YAML WorkflowSpec: rag_automation_case_generation"
    assert result.task_type == "api_test_draft"
    assert result.intent == "rag_automation_case_generation"
    assert result.review_status == "write_approved"
    assert "mvp_context_loader_node" in result.executed_nodes
    assert "api_test_generation_node" in result.executed_nodes
    assert "artifact_preview_writer_node" in result.executed_nodes
    assert "prompts/rag-automation-case-prompt.md" in result.loaded_files
    preview = repo_root / result.output_paths["api_test_draft"]
    assert preview.is_file()
    assert preview.with_name(API_CASES_YAML_FILENAME).is_file()
    assert preview.with_name(API_RAG_RUN_RECORD_FILENAME).is_file()
    assert not (repo_root / "prd/demo-requirement/artifacts/api-test-cases.yml").exists()


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

    assert resumed.success
    assert resumed.review_status == "confirmed"
    assert "artifact_promoter_node" in resumed.executed_nodes
    formal = repo_root / "prd/demo-requirement/artifacts/api-test-draft.md"
    assert formal.is_file()
    assert "status: confirmed" in formal.read_text(encoding="utf-8")
    formal_yaml = repo_root / "prd/demo-requirement" / API_CASES_FORMAL_PATH
    assert formal_yaml.is_file()
    payload = yaml.safe_load(formal_yaml.read_text(encoding="utf-8"))
    assert payload["status"] == "confirmed"
    assert payload["human_review_required"] is False
    assert payload["source_artifact"] == "artifacts/api-test-draft.md"
    assert payload["promoted_from_run"] == result.run_id
    assert any(path.endswith("api-test-cases.yml") for path in resumed.output_paths.values())
    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/api-test-draft.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["status"] == "confirmed"


def test_api_test_draft_needs_changes_routes_to_reviser_and_interrupts_again(tmp_path):
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
        action="revise",
        user_input="补充鉴权失败场景",
        review_notes="补充鉴权失败场景",
        target_artifact="api_test_draft",
        repo_root=repo_root,
    )

    assert resumed.success
    assert resumed.run_status == "interrupted"
    assert resumed.review_status == "needs_human_review"
    assert resumed.next_action == "wait_for_review"
    assert "api_test_revision_node" in resumed.executed_nodes
    assert "artifact_preview_writer_node" in resumed.executed_nodes
    assert resumed.human_review["interrupt"]
    preview = repo_root / f"prd/demo-requirement/runs/{result.run_id}/artifact-preview.md"
    assert "自动修订记录" in preview.read_text(encoding="utf-8")
    assert not (repo_root / "prd/demo-requirement/artifacts/api-test-draft.md").exists()


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
        debug_artifacts={API_CASES_YAML_DEBUG_KEY: "cases: []\n"},
    )

    checked = api_test_quality_check_node(state, repo_root)

    assert any("缺少章节: 断言策略" in error for error in checked.quality_errors)
    assert any("待补充接口文档" in error for error in checked.quality_errors)
    assert any("执行结论" in error for error in checked.quality_errors)
    assert any("schema_version" in error for error in checked.quality_errors)


def test_api_test_quality_rejects_cases_without_source_refs(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    payload = {
        "schema_version": "agentic-qa.api-cases.v1",
        "status": "needs_human_review",
        "human_review_required": True,
        "base_url_env": "AGENTIC_QA_BASE_URL",
        "business_rules": ["登录规则"],
        "source_refs": [
            {
                "source_type": "prd",
                "source_path": "prd/demo-requirement/input/requirement.md",
                "chunk_id": "rule-001",
                "locator": "登录规则",
                "summary": "登录规则",
                "confidence": "high",
            }
        ],
        "cases": [
            {
                "id": "API-001",
                "title": "登录成功",
                "method": "POST",
                "path": "/api/v1/auth/login",
                "business_rule_refs": ["登录规则"],
                "request": {},
                "expected": {"status_code": [200]},
                "pending": [],
            }
        ],
    }
    state = QAWorkflowState(
        user_input="生成接口测试草稿",
        prd_path="prd/demo-requirement",
        task_type="api_test_draft",
        run_id="run-1",
        draft_artifacts={
            "api_test_draft": "\n".join(
                f"## {index}. {section}"
                for index, section in enumerate(
                    [
                        "接口清单",
                        "接口测试点矩阵",
                        "请求示例",
                        "pytest + requests 脚本草稿",
                        "断言策略",
                        "测试数据准备建议",
                        "环境与鉴权待补充项",
                        "风险与限制",
                    ],
                    start=1,
                )
            )
            + "\n\n待补充接口文档",
        },
        output_paths={"api_test_draft": "prd/demo-requirement/runs/run-1/artifact-preview.md"},
        loaded_files={},
        debug_artifacts={API_CASES_YAML_DEBUG_KEY: yaml.safe_dump(payload, allow_unicode=True)},
    )

    checked = api_test_quality_check_node(state, repo_root)

    assert any("source_refs" in error for error in checked.quality_errors)
    assert any("review_status" in error for error in checked.quality_errors)
