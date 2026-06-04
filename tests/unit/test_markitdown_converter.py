from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.tools import document_converter  # noqa: E402
from runtime.tools.document_converter import convert_requirement_to_markdown  # noqa: E402


def test_convert_requirement_txt_to_markdown(tmp_path):
    source = tmp_path / "requirement.txt"
    output = tmp_path / "input/requirement.md"
    source.write_text("# Login Requirement\n\nUser can login.", encoding="utf-8")

    markdown = convert_requirement_to_markdown(source, output)

    assert output.is_file()
    assert "Login Requirement" in markdown
    assert output.read_text(encoding="utf-8").endswith("\n")


def test_convert_requirement_does_not_overwrite_existing_markdown(tmp_path):
    source = tmp_path / "requirement.txt"
    output = tmp_path / "input/requirement.md"
    source.write_text("new requirement", encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("human markdown", encoding="utf-8")

    try:
        convert_requirement_to_markdown(source, output)
    except FileExistsError as exc:
        assert "默认不覆盖" in str(exc)
    else:
        raise AssertionError("expected FileExistsError")

    assert output.read_text(encoding="utf-8") == "human markdown"


def test_convert_requirement_returns_clear_error_when_markitdown_fails(tmp_path, monkeypatch):
    source = tmp_path / "requirement.txt"
    output = tmp_path / "input/requirement.md"
    source.write_text("source", encoding="utf-8")

    class FakeMarkItDown:
        def convert(self, source_path):
            raise RuntimeError("boom")

    monkeypatch.setattr(document_converter, "MarkItDown", lambda: FakeMarkItDown())

    try:
        convert_requirement_to_markdown(source, output)
    except RuntimeError as exc:
        assert "MarkItDown 转换失败" in str(exc)
        assert "boom" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert not output.exists()
