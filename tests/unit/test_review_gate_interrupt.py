from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_runtime_mvp_generation import create_mvp_repo, write_file  # noqa: E402

from runtime.graph.mvp_graph import (  # noqa: E402
    promote_mvp_artifacts,
    run_mvp_analysis_and_testcases_workflow,
    run_mvp_testcase_generation_workflow,
)
from runtime.workflow.runner import resume_workflow_for_run  # noqa: E402


@pytest.fixture(autouse=True)
def disable_real_llm_by_default(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


def read_review(repo_root: Path, name: str) -> dict:
    path = repo_root / "prd/demo-requirement/reviews" / name
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_review_status(repo_root: Path, name: str, *, status: str, run_id: str) -> None:
    path = repo_root / "prd/demo-requirement/reviews" / name
    review = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    review["status"] = status
    review["decision"] = status
    review["run_id"] = run_id
    path.write_text(
        yaml.safe_dump(review, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_unreviewed_workflow_interrupts_with_review_payload(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
    )

    assert result.success
    assert result.review_status == "needs_human_review"
    assert result.next_action == "wait_for_review"
    assert result.run_status == "interrupted"
    assert result.human_review["interrupt"]
    payload = result.human_review["interrupt"][0]["value"]
    assert payload["run_id"] == result.run_id
    assert payload["prd_path"] == "prd/demo-requirement"
    assert payload["artifact_keys"] == ["requirement_analysis", "testcases"]
    assert payload["review_status"] == "needs_human_review"
    assert payload["preview_path"].endswith("/artifact-preview.md")
    assert payload["allowed_actions"] == ["approve", "reject", "revise"]
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_single_artifact_approve_can_omit_target_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
    )

    resumed = resume_workflow_for_run(
        result.run_id or "",
        action="approve",
        reviewed_by="qa",
        review_notes="通过",
        repo_root=repo_root,
    )

    assert resumed.success
    assert resumed.review_status == "approved"
    assert resumed.next_action == "promote"
    assert resumed.run_status == "completed"
    assert resumed.human_review["decision"]["target_artifact"] == "testcases"
    assert read_review(repo_root, "testcases.review.yml")["status"] == "approved"
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_multi_artifact_approve_requires_target_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
    )

    resumed = resume_workflow_for_run(
        result.run_id or "",
        action="approve",
        reviewed_by="qa",
        repo_root=repo_root,
    )

    assert not resumed.success
    assert resumed.review_status == "needs_human_review"
    assert resumed.next_action == "wait_for_review"
    assert resumed.run_status == "interrupted"
    assert any("target_artifact" in error for error in resumed.errors)
    assert "artifact_preview_writer_node" not in resumed.executed_nodes


def test_multi_artifact_approve_rejects_invalid_target_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
    )

    resumed = resume_workflow_for_run(
        result.run_id or "",
        action="approve",
        reviewed_by="qa",
        target_artifact="api_tests",
        repo_root=repo_root,
    )

    assert not resumed.success
    assert resumed.review_status == "needs_human_review"
    assert resumed.next_action == "wait_for_review"
    assert any("api_tests" in error for error in resumed.errors)
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_multi_artifact_approve_single_target_only_approves_that_review(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
    )

    resumed = resume_workflow_for_run(
        result.run_id or "",
        action="approve",
        reviewed_by="qa",
        review_notes="只通过测试用例",
        target_artifact="testcases",
        repo_root=repo_root,
    )

    assert resumed.success
    assert resumed.review_status == "approved"
    assert resumed.next_action == "promote"
    assert read_review(repo_root, "testcases.review.yml")["status"] == "approved"
    assert read_review(repo_root, "requirement-analysis.review.yml")["status"] == (
        "needs_human_review"
    )

    promoted = promote_mvp_artifacts(
        "prd/demo-requirement",
        result.run_id or "",
        repo_root=repo_root,
    )

    assert promoted.success
    assert promoted.review_status == "confirmed"
    assert promoted.output_paths == {"testcases": "prd/demo-requirement/artifacts/testcases.md"}
    assert (repo_root / "prd/demo-requirement/artifacts/testcases.md").is_file()
    assert not (repo_root / "prd/demo-requirement/artifacts/requirement-analysis.md").exists()


def test_multi_artifact_all_target_approves_all_reviews(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
    )

    resumed = resume_workflow_for_run(
        result.run_id or "",
        action="approve",
        reviewed_by="qa",
        target_artifact="all",
        repo_root=repo_root,
    )

    assert resumed.success
    assert resumed.review_status == "approved"
    assert read_review(repo_root, "testcases.review.yml")["status"] == "approved"
    assert read_review(repo_root, "requirement-analysis.review.yml")["status"] == "approved"


def test_reject_without_target_defaults_to_all_for_multi_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
    )

    resumed = resume_workflow_for_run(
        result.run_id or "",
        action="reject",
        reviewed_by="qa",
        repo_root=repo_root,
    )

    assert resumed.success
    assert resumed.review_status == "rejected"
    assert resumed.next_action == "stop"
    assert resumed.run_status == "rejected"
    assert resumed.human_review["decision"]["target_artifact"] == "all"
    assert not resumed.wrote_file


def test_revise_requires_target_for_multi_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_analysis_and_testcases_workflow(
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
        repo_root=repo_root,
    )

    assert not resumed.success
    assert resumed.review_status == "needs_human_review"
    assert resumed.next_action == "wait_for_review"
    assert any("target_artifact" in error for error in resumed.errors)


@pytest.mark.parametrize("action", ["confirmed", "publish", ""])
def test_illegal_resume_action_cannot_promote_or_confirm(tmp_path, action):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
    )

    resumed = resume_workflow_for_run(
        result.run_id or "",
        action=action,
        reviewed_by="qa",
        repo_root=repo_root,
    )

    assert not resumed.success
    assert resumed.review_status == "needs_human_review"
    assert resumed.next_action == "wait_for_review"
    assert any("不支持的 Review Gate action" in error for error in resumed.errors)
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


@pytest.mark.parametrize("status", ["needs_human_review", "needs_changes", "rejected", "confirmed"])
def test_promote_rejects_non_approved_review_statuses(tmp_path, status):
    repo_root = create_mvp_repo(tmp_path)
    write_file(repo_root / "prd/demo-requirement/artifacts/testcases.md", "旧版测试用例")
    run_id = "runtime"
    run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
        record_run=False,
    )
    write_review_status(
        repo_root,
        "testcases.review.yml",
        status=status,
        run_id=run_id,
    )

    promoted = promote_mvp_artifacts(
        "prd/demo-requirement",
        run_id,
        repo_root=repo_root,
        task_type="testcase_generation",
    )

    assert not promoted.success
    assert any("approved" in error for error in promoted.errors)
    assert (repo_root / "prd/demo-requirement/artifacts/testcases.md").read_text(
        encoding="utf-8"
    ) == "旧版测试用例"


def test_confirmed_status_only_comes_from_promote_artifacts(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=True,
    )

    resumed = resume_workflow_for_run(
        result.run_id or "",
        action="approve",
        reviewed_by="qa",
        repo_root=repo_root,
    )

    assert resumed.review_status == "approved"
    assert resumed.review_status != "confirmed"

    promoted = promote_mvp_artifacts(
        "prd/demo-requirement",
        result.run_id or "",
        repo_root=repo_root,
        task_type="testcase_generation",
    )

    assert promoted.success
    assert promoted.review_status == "confirmed"
    assert promoted.run_status == "completed"
