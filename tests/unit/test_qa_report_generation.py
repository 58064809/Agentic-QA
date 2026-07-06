from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime_mvp_fixtures import build_valid_testcases, create_mvp_repo  # noqa: E402

from runtime.graph.app import (  # noqa: E402
    promote_artifacts,
    resume_recorded_workflow,
    run_qa_report_workflow,
)
from runtime.graph.nodes.qa_report_generation import qa_report_quality_check_node  # noqa: E402
from runtime.graph.state import QAWorkflowState  # noqa: E402
from runtime.llm.config import OpenAICompatibleConfig  # noqa: E402
from runtime.llm.intent_router import route_intent  # noqa: E402
from runtime.workspace import ARTIFACT_SPECS  # noqa: E402


def add_qa_report_context_files(repo_root: Path) -> None:
    files = {
        "docs/qa-report-generation.md": (REPO_ROOT / "docs/qa-report-generation.md").read_text(
            encoding="utf-8"
        ),
        "prompts/report-generation-prompt.md": (
            REPO_ROOT / "prompts/report-generation-prompt.md"
        ).read_text(encoding="utf-8"),
        "skills/reporting/qa-report-writing-skill.md": (
            REPO_ROOT / "skills/reporting/qa-report-writing-skill.md"
        ).read_text(encoding="utf-8"),
        "workflows/runtime/qa-report.workflow.yml": (
            REPO_ROOT / "workflows/runtime/qa-report.workflow.yml"
        ).read_text(encoding="utf-8"),
    }
    for relative_path, content in files.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def seed_formal_qa_inputs(repo_root: Path) -> None:
    prd = repo_root / "prd/demo-requirement"
    (prd / "artifacts").mkdir(parents=True, exist_ok=True)
    (prd / "reviews").mkdir(parents=True, exist_ok=True)
    (prd / "artifacts/requirement-analysis.md").write_text(
        "---\nstatus: confirmed\nartifact_type: requirement_analysis\n---\n\n"
        "# 需求分析\n\n## 11. 待确认问题\n\n- 锁定策略待确认\n",
        encoding="utf-8",
    )
    (prd / "artifacts/testcases.md").write_text(
        build_valid_testcases(15),
        encoding="utf-8",
    )
    (prd / "artifacts/api-test-draft.md").write_text(
        "---\nstatus: confirmed\nartifact_type: api_test_draft\n---\n\n# 接口测试草稿\n",
        encoding="utf-8",
    )
    for review_name in (
        "requirement-analysis.review.yml",
        "testcases.review.yml",
        "api-test-draft.review.yml",
    ):
        (prd / "reviews" / review_name).write_text(
            "status: confirmed\nrun_id: run-seed\nnext_action: ''\n",
            encoding="utf-8",
        )


def test_qa_report_artifact_spec_is_registered():
    spec = ARTIFACT_SPECS["qa_report"]

    assert spec["current_path"] == "artifacts/qa-report.md"
    assert spec["review_path"] == "reviews/qa-report.review.yml"


def test_intent_routes_qa_report_without_llm(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    route = route_intent(
        "基于 prd/demo-requirement 生成 QA 报告",
        OpenAICompatibleConfig.from_env(),
    )

    assert route.is_valid
    assert route.intent == "qa_report"
    assert route.prd_path == "prd/demo-requirement"


def test_qa_report_fallback_writes_reviewable_preview(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_qa_report_context_files(repo_root)
    seed_formal_qa_inputs(repo_root)

    result = run_qa_report_workflow(
        "生成 QA 报告",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
        use_llm=False,
    )

    assert result.success
    assert result.quality_errors == []
    assert result.output_paths == {
        "qa_report": f"prd/demo-requirement/runs/{result.run_id}/artifact-preview.md"
    }
    preview = (repo_root / result.output_paths["qa_report"]).read_text(encoding="utf-8")
    assert "artifact_type: qa_report" in preview
    assert "## 4. 执行概况" in preview
    assert "通过率 | 待确认" in preview
    assert "准许发布" not in preview
    assert not (repo_root / "prd/demo-requirement/artifacts/qa-report.md").exists()


def test_qa_report_promote_writes_formal_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    add_qa_report_context_files(repo_root)
    seed_formal_qa_inputs(repo_root)

    result = run_qa_report_workflow(
        "生成 QA 报告",
        "prd/demo-requirement",
        repo_root=repo_root,
        use_llm=False,
    )
    resumed = resume_recorded_workflow(
        result.run_id or "",
        action="approve",
        user_input="QA 报告通过",
        target_artifact="qa_report",
        repo_root=repo_root,
    )
    promoted = promote_artifacts(
        "prd/demo-requirement",
        result.run_id or "",
        repo_root=repo_root,
        task_type="qa_report",
    )

    assert resumed.success
    assert promoted.success
    formal = repo_root / "prd/demo-requirement/artifacts/qa-report.md"
    assert formal.is_file()
    assert "status: confirmed" in formal.read_text(encoding="utf-8")
    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/qa-report.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["status"] == "confirmed"


def test_qa_report_quality_rejects_fake_execution_conclusion(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    artifact = """---
status: needs_human_review
artifact_type: qa_report
human_review_required: true
---

# QA 报告草稿

## 1. 基本信息
内容
## 2. 产物索引
内容
## 3. 测试范围
内容
## 4. 执行概况
通过率: 100%，全部通过
## 5. 缺陷和风险
内容
## 6. 未覆盖范围
内容
## 7. 结论草稿
可以上线
## 8. 待人工确认项
- [ ] 待人工确认
"""
    state = QAWorkflowState(
        user_input="生成 QA 报告",
        prd_path="prd/demo-requirement",
        task_type="qa_report",
        run_id="run-1",
        draft_artifacts={"qa_report": artifact},
        output_paths={"qa_report": "prd/demo-requirement/runs/run-1/artifact-preview.md"},
    )

    checked = qa_report_quality_check_node(state, repo_root)

    assert any("不得伪造执行通过率" in error for error in checked.quality_errors)
