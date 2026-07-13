from __future__ import annotations

import yaml

import runtime.cli as cli
from runtime.cli import importer, promoter


def test_import_markdown_requirement_creates_prd_workspace(tmp_path):
    markdown = "# Login Requirement\n\n## Scope\n\n- Password login"

    prd_rel = cli._import_markdown_requirement(
        tmp_path,
        markdown,
        title="Login Requirement",
    )

    workspace = tmp_path / prd_rel
    assert (workspace / "input/requirement.md").read_text(encoding="utf-8") == markdown + "\n"
    metadata = yaml.safe_load((workspace / "metadata.yml").read_text(encoding="utf-8"))
    assert metadata["source_type"] == "manual_markdown"


def test_import_feishu_url_normalizes_to_requirement_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "is_feishu_url", lambda url: True)
    monkeypatch.setattr(
        cli,
        "fetch_feishu_doc",
        lambda url: ("Feishu Requirement", "# Feishu Requirement\n\n## Scope\n\n- Sync docs"),
    )

    prd_rel = cli._import_feishu_url(tmp_path, "https://example.feishu.cn/docx/abc123")

    workspace = tmp_path / prd_rel
    assert "Sync docs" in (workspace / "input/requirement.md").read_text(encoding="utf-8")
    metadata = yaml.safe_load((workspace / "metadata.yml").read_text(encoding="utf-8"))
    assert metadata["source_type"] == "feishu"
    assert metadata["source_url"] == "https://example.feishu.cn/docx/abc123"


def test_ensure_prd_workspace_imports_relative_markdown_file(tmp_path):
    prd_root = tmp_path / "prd"
    prd_root.mkdir()
    source = prd_root / "城市开局计划 H5 规则.md"
    source.write_text("# 城市开局计划 H5 规则\n\n## 范围\n\n- H5 展示规则", encoding="utf-8")

    prd_rel = cli._ensure_prd_workspace(tmp_path, "prd/城市开局计划 H5 规则.md")

    assert prd_rel == "prd/城市开局计划H5规则"
    assert not (tmp_path / "prd/城市开局计划 H5 规则.md").is_dir()
    workspace = tmp_path / prd_rel
    assert "H5 展示规则" in (workspace / "input/requirement.md").read_text(encoding="utf-8")


def test_inline_markdown_detection():
    assert cli._looks_like_markdown_requirement("# Title\n\n## Scope\n\n- item")
    assert not cli._looks_like_markdown_requirement("analyze prd/demo")
    assert not hasattr(importer, "_looks_like_markdown_requirement")


def test_cli_package_reexports_promoter_run_workflow():
    assert cli._run_workflow is promoter._run_workflow


def test_extract_prd_workspace_path_from_natural_language():
    assert (
        cli._extract_prd_workspace_path("分析 prd/demo-requirement 并生成测试用例")
        == "prd/demo-requirement"
    )
