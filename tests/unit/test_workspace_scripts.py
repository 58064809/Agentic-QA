from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from create_prd_workspace import (  # noqa: E402
    WORKSPACE_DIRS,
    archive_requirement,
    create_workspace,
    generate_markdown_report,
    read_yaml,
    validate_workspace,
    write_yaml,
)

from runtime.workspace import ARTIFACT_SPECS, REQUIRED_WORKSPACE_FILES  # noqa: E402


def test_create_prd_workspace_creates_standard_directories(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")

    assert (workspace / "input/requirement.md").is_file()
    assert (workspace / "input/api.md").is_file()
    assert (workspace / "metadata.yml").is_file()
    assert (workspace / "reviews/testcases.review.yml").is_file()
    assert (workspace / "artifacts/history/testcases/index.yml").is_file()
    for spec in ARTIFACT_SPECS.values():
        assert (workspace / spec["review_path"]).is_file()
        assert (workspace / spec["history_index"]).is_file()
    for directory in WORKSPACE_DIRS:
        assert (workspace / directory).is_dir()


def test_validate_prd_workspace_accepts_standard_workspace(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")

    result = validate_workspace(workspace)

    assert result.ok, result.errors


def test_generate_markdown_report_creates_report_draft(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")

    report = generate_markdown_report(workspace)
    content = report.read_text(encoding="utf-8")

    assert report.is_file()
    assert report == workspace / "artifacts/qa-report.md"
    assert "QA 报告草稿" in content
    assert "产物索引" in content
    assert "待人工确认项" in content


def test_archive_requirement_rejects_unreviewed_workspace(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")

    with pytest.raises(RuntimeError, match="拒绝归档"):
        archive_requirement(workspace)


def test_archive_requirement_accepts_confirmed_reviews(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")
    for review_path in (workspace / "reviews").glob("*.review.yml"):
        record = read_yaml(review_path)
        record["status"] = "confirmed"
        record["decision"] = "confirmed"
        write_yaml(review_path, record)

    archive_index = archive_requirement(workspace)

    assert archive_index == workspace / "artifacts/archive-index.md"
    assert archive_index.is_file()
    metadata = read_yaml(workspace / "metadata.yml")
    assert metadata["status"] == "archived"


def test_validate_workspace_rejects_invalid_review_status(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")
    review_path = workspace / "reviews/testcases.review.yml"
    record = read_yaml(review_path)
    record["status"] = "unknown"
    write_yaml(review_path, record)

    result = validate_workspace(workspace)

    assert not result.ok
    assert any("status 非法" in error for error in result.errors)


def test_validate_workspace_detects_missing_generated_review_and_history(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")
    (workspace / "reviews/ui-test-draft.review.yml").unlink()
    (workspace / "artifacts/history/api-discovery-report/index.yml").unlink()

    result = validate_workspace(workspace)

    assert not result.ok
    assert "缺少文件: reviews/ui-test-draft.review.yml" in result.errors
    assert "缺少文件: artifacts/history/api-discovery-report/index.yml" in result.errors


def test_create_workspace_does_not_overwrite_existing_review_or_history(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")
    review = workspace / "reviews/ui-test-draft.review.yml"
    history = workspace / "artifacts/history/ui-test-draft/index.yml"
    review.write_text("status: approved\ncustom: keep\n", encoding="utf-8")
    history.write_text("artifact: custom\nversions:\n- v1\n", encoding="utf-8")

    create_workspace("demo-requirement", prd_root=tmp_path / "prd")

    assert "custom: keep" in review.read_text(encoding="utf-8")
    assert "- v1" in history.read_text(encoding="utf-8")


def test_required_workspace_files_are_derived_from_artifact_specs():
    for spec in ARTIFACT_SPECS.values():
        assert spec["review_path"] in REQUIRED_WORKSPACE_FILES
        assert spec["history_index"] in REQUIRED_WORKSPACE_FILES
