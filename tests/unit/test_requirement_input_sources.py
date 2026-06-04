from __future__ import annotations

import yaml

import runtime.cli as cli


def test_import_markdown_requirement_creates_prd_workspace(tmp_path):
    markdown = "# Login Requirement\n\n## Scope\n\n- Password login"

    prd_rel = cli._import_markdown_requirement(
        tmp_path,
        markdown,
        title="Login Requirement",
    )

    workspace = tmp_path / prd_rel
    assert (workspace / "input/requirement.md").read_text(encoding="utf-8") == markdown + "\n"
    metadata = yaml.safe_load((workspace / "workspace.yml").read_text(encoding="utf-8"))
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
    metadata = yaml.safe_load((workspace / "workspace.yml").read_text(encoding="utf-8"))
    assert metadata["source_type"] == "feishu"
    assert metadata["source_url"] == "https://example.feishu.cn/docx/abc123"


def test_inline_markdown_detection():
    assert cli._looks_like_markdown_requirement("# Title\n\n## Scope\n\n- item")
    assert not cli._looks_like_markdown_requirement("analyze prd/demo")
