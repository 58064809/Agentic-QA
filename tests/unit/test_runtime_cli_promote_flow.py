from __future__ import annotations

import pytest
import yaml
from runtime_mvp_fixtures import create_mvp_repo, write_promote_fixture

import runtime.cli as cli
from runtime.graph.mvp_graph import (
    run_mvp_analysis_and_testcases_workflow,
    run_mvp_testcase_generation_workflow,
)


def test_cli_natural_language_promote_approves_and_publishes_testcases(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )

    prd_rel, promoted = cli._run_natural_promote_request(
        "测试用例通过，发布正式产物 prd/demo-requirement",
        repo_root,
    )

    assert prd_rel == "prd/demo-requirement"
    assert promoted.success
    assert promoted.output_paths == {"testcases": "prd/demo-requirement/artifacts/testcases.md"}
    assert (repo_root / "prd/demo-requirement/artifacts/testcases.md").is_file()
    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/testcases.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["status"] == "confirmed"
    assert review["decision"] == "promoted"
    assert review["promoted_run_id"] == result.run_id


def test_cli_natural_language_plain_approve_promotes_single_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    prd_rel, promoted = cli._run_natural_promote_request(
        "通过",
        repo_root,
        fallback_prd="prd/demo-requirement",
    )

    assert prd_rel == "prd/demo-requirement"
    assert promoted.success
    assert promoted.review_status == "confirmed"
    assert promoted.output_paths == {"testcases": "prd/demo-requirement/artifacts/testcases.md"}
    assert (repo_root / "prd/demo-requirement/artifacts/testcases.md").is_file()
    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/testcases.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["promoted_run_id"] == result.run_id


def test_cli_natural_language_promote_resumes_interrupted_run_before_promote(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_analysis_and_testcases_workflow(
        "璇峰垎鏋愰渶姹傚苟鐢熸垚娴嬭瘯鐢ㄤ緥",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    prd_rel, promoted = cli._run_natural_promote_request(
        "娴嬭瘯鐢ㄤ緥閫氳繃锛屽彂甯冩寮忎骇鐗?prd/demo-requirement",
        repo_root,
    )

    assert prd_rel == "prd/demo-requirement"
    assert promoted.success
    assert promoted.review_status == "confirmed"
    assert promoted.output_paths == {"testcases": "prd/demo-requirement/artifacts/testcases.md"}
    assert (repo_root / "prd/demo-requirement/artifacts/testcases.md").is_file()
    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/testcases.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["status"] == "confirmed"
    assert review["decision"] == "promoted"
    assert review["promoted_run_id"] == result.run_id
    review_events = repo_root / ".runtime" / "runs" / (result.run_id or "") / "review-events.jsonl"
    assert review_events.is_file()
    assert "cli" in review_events.read_text(encoding="utf-8")


def test_cli_natural_language_promote_clarifies_multi_artifact_without_target(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    run_mvp_analysis_and_testcases_workflow(
        "璇峰垎鏋愰渶姹傚苟鐢熸垚娴嬭瘯鐢ㄤ緥",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    with pytest.raises(ValueError) as excinfo:
        cli._run_natural_promote_request(
            "閫氳繃锛屽彂甯冩寮忎骇鐗?prd/demo-requirement",
            repo_root,
        )

    message = str(excinfo.value)
    assert "requirement_analysis" in message
    assert "testcases" in message
    assert "只发布测试用例" in message
    assert "只发布需求分析" in message
    assert "全部发布" in message
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()
    assert not (repo_root / "prd/demo-requirement/artifacts/requirement-analysis.md").exists()


def test_cli_natural_language_plain_approve_clarifies_multi_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    with pytest.raises(ValueError) as excinfo:
        cli._run_natural_promote_request(
            "通过",
            repo_root,
            fallback_prd="prd/demo-requirement",
        )

    assert "requirement_analysis" in str(excinfo.value)
    assert "testcases" in str(excinfo.value)
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()
    assert not (repo_root / "prd/demo-requirement/artifacts/requirement-analysis.md").exists()


def test_cli_natural_language_promote_all_publishes_multi_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_analysis_and_testcases_workflow(
        "璇峰垎鏋愰渶姹傚苟鐢熸垚娴嬭瘯鐢ㄤ緥",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    prd_rel, promoted = cli._run_natural_promote_request(
        "全部通过，全部发布 prd/demo-requirement",
        repo_root,
    )

    assert prd_rel == "prd/demo-requirement"
    assert promoted.success
    assert promoted.review_status == "confirmed"
    assert promoted.output_paths == {
        "requirement_analysis": "prd/demo-requirement/artifacts/requirement-analysis.md",
        "testcases": "prd/demo-requirement/artifacts/testcases.md",
    }
    assert (repo_root / "prd/demo-requirement/artifacts/requirement-analysis.md").is_file()
    assert (repo_root / "prd/demo-requirement/artifacts/testcases.md").is_file()
    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/testcases.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["promoted_run_id"] == result.run_id


def test_cli_natural_language_approve_runs_state_machine_to_confirmed(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    prd_rel, approved = cli._run_natural_promote_request(
        "通过并发布",
        repo_root,
        fallback_prd="prd/demo-requirement",
    )

    assert prd_rel == "prd/demo-requirement"
    assert approved.success
    assert approved.review_status == "confirmed"
    assert (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()
    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/testcases.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["status"] == "confirmed"
    assert review["decision"] == "promoted"


def test_cli_natural_language_plain_approve_requires_context(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    with pytest.raises(ValueError):
        cli._run_natural_promote_request("通过", repo_root)


def test_cli_promote_command_publishes_selected_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )

    exit_code = cli._run_promote_command(
        ["prd/demo-requirement", result.run_id or "", "testcases"],
        repo_root,
    )

    assert exit_code == 0
    assert (repo_root / "prd/demo-requirement/artifacts/testcases.md").is_file()
    assert not (repo_root / "prd/demo-requirement/artifacts/requirement-analysis.md").exists()


def test_cli_promote_command_without_artifact_uses_latest_ui_run_keys(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    write_promote_fixture(repo_root, artifact_keys=["ui_test_draft"])

    exit_code = cli._run_promote_command(["prd/demo-requirement"], repo_root)

    assert exit_code == 0
    assert (repo_root / "prd/demo-requirement/artifacts/ui-test-draft.md").is_file()
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_cli_promote_command_without_artifact_uses_latest_api_discovery_run_keys(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    write_promote_fixture(repo_root, artifact_keys=["api_discovery_report"])

    exit_code = cli._run_promote_command(["prd/demo-requirement"], repo_root)

    assert exit_code == 0
    assert (repo_root / "prd/demo-requirement/artifacts/api-discovery-report.md").is_file()
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_cli_promote_command_without_artifact_uses_latest_qa_report_run_keys(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    write_promote_fixture(repo_root, artifact_keys=["qa_report"])

    exit_code = cli._run_promote_command(["prd/demo-requirement"], repo_root)

    assert exit_code == 0
    assert (repo_root / "prd/demo-requirement/artifacts/qa-report.md").is_file()
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_cli_promote_command_without_artifact_publishes_latest_mvp_run_keys(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    write_promote_fixture(repo_root, artifact_keys=["requirement_analysis", "testcases"])

    exit_code = cli._run_promote_command(["prd/demo-requirement"], repo_root)

    assert exit_code == 0
    assert (repo_root / "prd/demo-requirement/artifacts/requirement-analysis.md").is_file()
    assert (repo_root / "prd/demo-requirement/artifacts/testcases.md").is_file()


def test_cli_resume_command_approves_and_promotes_single_artifact(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    exit_code = cli._run_resume_command(
        [result.run_id or "", "测试用例通过，发布正式产物"],
        repo_root,
    )

    assert exit_code == 0
    assert (repo_root / "prd/demo-requirement/artifacts/testcases.md").is_file()
    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/testcases.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["status"] == "confirmed"
    assert review["decision"] == "promoted"


def test_cli_resume_command_hold_keeps_waiting_review(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    exit_code = cli._run_resume_command(
        [result.run_id or "", "先不要发布"],
        repo_root,
    )

    assert exit_code == 0
    review_path = repo_root / "prd/demo-requirement/reviews/testcases.review.yml"
    if review_path.exists():
        review = yaml.safe_load(review_path.read_text(encoding="utf-8")) or {}
        assert review.get("status") != "approved"
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_cli_resume_command_retry_failed_run(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    requirement_path = repo_root / "prd/demo-requirement/input/requirement.md"
    original = requirement_path.read_text(encoding="utf-8")
    requirement_path.unlink()
    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )
    assert not result.success
    requirement_path.write_text(original, encoding="utf-8")

    exit_code = cli._run_resume_command(
        [result.run_id or "", "重试"],
        repo_root,
    )

    assert exit_code == 0
    assert (repo_root / f"prd/demo-requirement/runs/{result.run_id}/artifact-preview.md").is_file()
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_cli_resume_command_multi_artifact_unclear_target_fails(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
    )

    exit_code = cli._run_resume_command(
        [result.run_id or "", "通过"],
        repo_root,
    )

    assert exit_code == 1
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()
    assert not (repo_root / "prd/demo-requirement/artifacts/requirement-analysis.md").exists()
