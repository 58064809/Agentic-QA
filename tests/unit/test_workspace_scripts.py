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
    validate_workspace,
)


def test_create_prd_workspace_creates_standard_directories(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")

    assert (workspace / "requirement.md").is_file()
    assert (workspace / "api-doc.md").is_file()
    assert (workspace / "metadata.yml").is_file()
    for directory in WORKSPACE_DIRS:
        assert (workspace / directory).is_dir()


def test_validate_prd_workspace_accepts_standard_workspace(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")

    result = validate_workspace(workspace)

    assert result.ok, result.errors


def test_generate_markdown_report_creates_report_draft(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")

    report = generate_markdown_report(workspace)

    assert report.is_file()
    assert "QA 报告草稿" in report.read_text(encoding="utf-8")


def test_archive_requirement_rejects_unreviewed_workspace(tmp_path):
    workspace = create_workspace("demo-requirement", prd_root=tmp_path / "prd")

    with pytest.raises(RuntimeError, match="拒绝归档"):
        archive_requirement(workspace)
