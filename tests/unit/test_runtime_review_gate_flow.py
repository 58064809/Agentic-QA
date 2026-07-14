from __future__ import annotations

import yaml
from runtime_fixtures import create_runtime_repo, write_file

from runtime.graph.app import (
    promote_artifacts,
    run_analysis_and_testcases_workflow,
)
from runtime.workflow.runner import resume_workflow_for_run


def test_interrupt_review_gate_approve_resume_writes_candidate_preview(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    result = run_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
    )

    assert result.run_status == "interrupted"
    assert result.review_status == "needs_human_review"
    interrupt_payload = result.human_review["interrupt"][0]["value"]
    assert interrupt_payload["run_id"] == result.run_id
    assert interrupt_payload["prd_path"] == "prd/demo-requirement"
    assert interrupt_payload["artifact_keys"] == ["requirement_analysis", "testcases"]
    assert interrupt_payload["review_status"] == "needs_human_review"
    assert interrupt_payload["preview_path"].endswith("/requirement-analysis.preview.md")
    assert interrupt_payload["allowed_actions"] == [
        "approve",
        "reject",
        "revise",
        "show_diff",
        "hold",
        "clarify",
    ]

    resumed = resume_workflow_for_run(
        result.run_id or "",
        action="approve",
        reviewed_by="qa",
        review_notes="通过",
        target_artifact="all",
        repo_root=repo_root,
    )

    assert resumed.success
    assert resumed.run_status == "completed"
    assert resumed.review_status == "confirmed"
    assert resumed.wrote_file
    assert "artifact_promoter" in resumed.executed_nodes
    preview_path = repo_root / resumed.output_paths["testcases"]
    assert preview_path.is_file()
    assert (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()
    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/testcases.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["status"] == "confirmed"
    assert review["decision"] == "promoted"


def test_interrupt_review_gate_reject_resume_stops_without_formal_artifact(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    result = run_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
    )

    resumed = resume_workflow_for_run(
        result.run_id or "",
        action="reject",
        reviewed_by="qa",
        review_notes="不通过",
        repo_root=repo_root,
    )

    assert resumed.success
    assert resumed.review_status == "rejected"
    assert resumed.next_action == "stop"
    assert resumed.run_status == "rejected"
    assert resumed.wrote_file
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_interrupt_review_gate_revise_resume_enters_needs_changes(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    result = run_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
    )

    resumed = resume_workflow_for_run(
        result.run_id or "",
        action="revise",
        reviewed_by="qa",
        review_notes="补充异常场景",
        target_artifact="testcases",
        repo_root=repo_root,
    )

    assert resumed.success
    assert resumed.review_status == "needs_changes"
    assert resumed.next_action == "revise"
    assert resumed.run_status == "needs_changes"
    assert resumed.human_review["decision"]["target_artifact"] == "testcases"
    assert resumed.wrote_file
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_promote_artifacts_requires_approved_reviews(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    result = run_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
        record_run=False,
    )

    promoted = promote_artifacts(
        "prd/demo-requirement",
        result.run_id or "runtime",
        repo_root=repo_root,
    )

    assert not promoted.success
    assert any("approved" in error for error in promoted.errors)
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_promote_artifacts_publishes_confirmed_preview(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    current_testcases = repo_root / "prd/demo-requirement/artifacts/testcases.md"
    write_file(current_testcases, "旧版测试用例")

    result = run_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
        record_run=False,
    )
    assert result.run_id is None
    run_id = "runtime"

    for review_name in ("requirement-analysis.review.yml", "testcases.review.yml"):
        review_path = repo_root / "prd/demo-requirement/reviews" / review_name
        review = yaml.safe_load(review_path.read_text(encoding="utf-8")) or {}
        review["status"] = "approved"
        review["decision"] = "approve"
        review["run_id"] = run_id
        review_path.write_text(
            yaml.safe_dump(review, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    promoted = promote_artifacts(
        "prd/demo-requirement",
        run_id,
        repo_root=repo_root,
    )

    analysis_path = repo_root / "prd/demo-requirement/artifacts/requirement-analysis.md"
    testcases_path = repo_root / "prd/demo-requirement/artifacts/testcases.md"
    assert promoted.success
    assert promoted.review_status == "confirmed"
    assert promoted.run_status == "completed"
    assert analysis_path.is_file()
    assert testcases_path.is_file()
    analysis_content = analysis_path.read_text(encoding="utf-8")
    testcases_content = testcases_path.read_text(encoding="utf-8")
    assert "artifact_type: artifact_preview" not in analysis_content
    assert "artifact_type: artifact_preview" not in testcases_content
    assert "status: confirmed" in analysis_content
    assert "status: confirmed" in testcases_content
    assert "| 鐢ㄤ緥ID |" not in analysis_content
    assert "## 12. 需求到测试覆盖映射" in analysis_path.read_text(encoding="utf-8")
    assert "| 用例ID |" in testcases_path.read_text(encoding="utf-8")
    history_dir = repo_root / "prd/demo-requirement/artifacts/history/testcases"
    assert list(history_dir.glob("*.previous.md"))

    metadata = yaml.safe_load(
        (repo_root / "prd/demo-requirement/metadata.yml").read_text(encoding="utf-8")
    )
    assert metadata["artifacts"]["testcases"]["status"] == "confirmed"
    assert metadata["artifacts"]["testcases"]["latest_run_id"] == run_id
    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/testcases.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["decision"] == "promoted"
