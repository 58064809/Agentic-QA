from __future__ import annotations

import json

import yaml
from runtime_fixtures import count_testcase_rows, create_runtime_repo, write_file

from runtime.graph.app import (
    promote_artifacts,
    run_analysis_and_testcases_workflow,
    run_requirement_analysis_workflow,
    run_testcase_generation_workflow,
)


def test_analyze_dry_run_generates_analysis_without_writing(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    assert result.task_type == "analysis"
    assert result.run_status == "interrupted"
    assert result.review_status == "needs_human_review"
    assert result.next_action == "wait_for_review"
    assert result.human_review["interrupt"]
    assert "requirement_analysis" in result.draft_artifacts
    analysis = result.draft_artifacts["requirement_analysis"]
    assert "needs_human_review" in analysis
    assert "## 1. 需求背景与目标" in analysis
    assert "## 12. 需求到测试覆盖映射" in analysis
    assert not (repo_root / "prd/demo-requirement/artifacts/requirement-analysis.md").exists()


def test_analyze_approve_write_creates_analysis_draft(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    output_path = repo_root / result.output_paths["requirement_analysis"]
    assert result.success
    assert output_path.exists()
    assert output_path.as_posix().endswith(
        f"/prd/demo-requirement/runs/{result.run_id}/requirement-analysis.preview.md"
    )
    structured_json = output_path.with_suffix(".json")
    structured_yaml = output_path.with_suffix(".yml")
    assert structured_json.exists()
    assert structured_yaml.exists()
    structured = json.loads(structured_json.read_text(encoding="utf-8"))
    assert structured["schema_version"] == "agentic-qa.artifact-preview.v1"
    assert structured["markdown_path"] == result.output_paths["requirement_analysis"]
    assert result.wrote_file
    assert result.review_status == "write_approved"
    assert "artifact_type: requirement_analysis" in output_path.read_text(encoding="utf-8")


def test_generate_testcases_dry_run_generates_testcases_without_writing(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    assert result.task_type == "testcase_generation"
    assert result.run_status == "interrupted"
    assert result.review_status == "needs_human_review"
    assert result.next_action == "wait_for_review"
    assert result.human_review["interrupt"]
    assert "testcases" in result.draft_artifacts
    testcases = result.draft_artifacts["testcases"]
    rich_header = (
        "| 用例ID | 需求/规则来源 | 标题 | 测试类型 | 优先级 | 前置条件 | 测试数据 | "
        "测试步骤 | 预期结果 | 断言/证据 | 待确认项 |"
    )
    assert rich_header in testcases
    assert count_testcase_rows(testcases) >= 15
    assert "用例类型" not in testcases.splitlines()[10:20]
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_generate_testcases_approve_write_creates_testcase_draft(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    output_path = repo_root / result.output_paths["testcases"]
    assert result.success
    assert result.wrote_file
    assert result.review_status == "write_approved"
    assert output_path.as_posix().endswith(
        f"/prd/demo-requirement/runs/{result.run_id}/testcases.preview.md"
    )
    assert "artifact_type: testcases" in output_path.read_text(encoding="utf-8")
    assert result.run_id in (repo_root / "prd/demo-requirement/runs/latest.yml").read_text(
        encoding="utf-8"
    )


def test_combined_dry_run_generates_two_drafts_without_writing(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    assert result.task_type == "analysis_and_testcases"
    assert result.run_status == "interrupted"
    assert result.review_status == "needs_human_review"
    assert result.next_action == "wait_for_review"
    assert "artifact_preview_writer" in result.executed_nodes
    assert result.wrote_file
    assert (repo_root / result.output_paths["testcases"]).is_file()
    assert set(result.draft_artifacts) == {"requirement_analysis", "testcases"}
    assert "## 12. 需求到测试覆盖映射" in result.draft_artifacts["requirement_analysis"]
    assert count_testcase_rows(result.draft_artifacts["testcases"]) >= 15
    assert not (repo_root / "prd/demo-requirement/artifacts/requirement-analysis.md").exists()
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_combined_approve_write_creates_analysis_and_testcases(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    assert result.success
    assert result.wrote_file
    assert result.review_status == "write_approved"
    analysis_path = repo_root / result.output_paths["requirement_analysis"]
    testcases_path = repo_root / result.output_paths["testcases"]
    assert analysis_path.is_file()
    assert testcases_path.is_file()
    assert analysis_path.as_posix().endswith(
        f"/prd/demo-requirement/runs/{result.run_id}/requirement-analysis.preview.md"
    )
    assert testcases_path.as_posix().endswith(
        f"/prd/demo-requirement/runs/{result.run_id}/testcases.preview.md"
    )
    assert (repo_root / f"prd/demo-requirement/runs/{result.run_id}/artifact-preview.md").is_file()
    assert (repo_root / "prd/demo-requirement/runs/latest.yml").is_file()
    assert (repo_root / "prd/demo-requirement/runs/index.jsonl").is_file()
    assert not (repo_root / "prd/demo-requirement/artifacts/requirement-analysis.md").exists()
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_debug_approve_preview_write_never_confirms_or_promotes(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = run_analysis_and_testcases_workflow(
        "璇峰垎鏋愰渶姹傚苟鐢熸垚娴嬭瘯鐢ㄤ緥",
        "prd/demo-requirement",
        repo_root=repo_root,
        debug_approve_preview_write=True,
    )

    assert result.success
    assert result.wrote_file
    assert result.approve_write is True
    assert result.debug_approve_preview_write is True
    assert result.review_status == "write_approved"
    assert result.review_status != "confirmed"
    assert result.human_review["decision"]["action"] == "debug_approve_preview_write"

    metadata = yaml.safe_load(
        (repo_root / "prd/demo-requirement/metadata.yml").read_text(encoding="utf-8")
    )
    assert metadata["status"] == "needs_human_review"
    assert metadata["artifacts"]["requirement_analysis"]["status"] == "needs_human_review"
    assert metadata["artifacts"]["testcases"]["status"] == "needs_human_review"

    review = yaml.safe_load(
        (repo_root / "prd/demo-requirement/reviews/testcases.review.yml").read_text(
            encoding="utf-8"
        )
    )
    assert review["status"] == "needs_human_review"
    assert review["decision"] == ""

    promoted = promote_artifacts(
        "prd/demo-requirement",
        result.run_id or "",
        repo_root=repo_root,
    )

    assert not promoted.success
    assert promoted.review_status != "confirmed"
    assert any("approved" in error for error in promoted.errors)
    assert not (repo_root / "prd/demo-requirement/artifacts/requirement-analysis.md").exists()
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_combined_approve_write_writes_run_candidates_when_defaults_exist(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    existing_analysis = repo_root / "prd/demo-requirement/artifacts/requirement-analysis.md"
    write_file(existing_analysis, "人工已有分析")

    result = run_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    assert result.success
    assert result.wrote_file
    assert existing_analysis.read_text(encoding="utf-8") == "人工已有分析"
    candidate_analysis = repo_root / result.output_paths["requirement_analysis"]
    candidate_testcases = repo_root / result.output_paths["testcases"]
    assert candidate_analysis.exists()
    assert candidate_analysis.with_suffix(".json").exists()
    assert candidate_analysis.with_suffix(".yml").exists()
    assert candidate_analysis.as_posix().endswith(
        f"/prd/demo-requirement/runs/{result.run_id}/requirement-analysis.preview.md"
    )
    assert candidate_testcases.exists()
    assert candidate_testcases.as_posix().endswith(
        f"/prd/demo-requirement/runs/{result.run_id}/testcases.preview.md"
    )
    latest = repo_root / "prd/demo-requirement/runs/latest.yml"
    index = repo_root / "prd/demo-requirement/runs/index.jsonl"
    assert latest.is_file()
    assert index.is_file()
    assert result.run_id in latest.read_text(encoding="utf-8")
    assert result.run_id in index.read_text(encoding="utf-8")
