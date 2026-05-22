from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from clean_markdown import clean_markdown_file, clean_markdown_text  # noqa: E402


def test_clean_markdown_text_removes_control_chars_and_keeps_chinese():
    text = "需求\x00标题\n\n\n需要  保留中文\x07\n"

    cleaned = clean_markdown_text(text)

    assert "\x00" not in cleaned
    assert "\x07" not in cleaned
    assert "需求标题" in cleaned
    assert "需要  保留中文" in cleaned


def test_clean_markdown_file_writes_cleaned_file_without_overwriting_source(tmp_path):
    source = tmp_path / "requirement.md"
    source.write_text("第一页\x00\n\n\n正文\f第二页\n", encoding="utf-8")

    output = clean_markdown_file(source)

    assert output == tmp_path / "requirement.cleaned.md"
    assert output.is_file()
    assert source.read_text(encoding="utf-8") == "第一页\x00\n\n\n正文\f第二页\n"
    assert "\x00" not in output.read_text(encoding="utf-8")


def test_clean_markdown_file_supports_explicit_overwrite(tmp_path):
    source = tmp_path / "requirement.md"
    source.write_text("正文\x00\n", encoding="utf-8")

    output = clean_markdown_file(source, overwrite=True)

    assert output == source.resolve()
    assert source.read_text(encoding="utf-8") == "正文\n"
