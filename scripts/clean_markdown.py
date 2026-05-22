"""Lightweight Markdown cleanup for converted requirement documents."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")
PAGE_MARKER_RE = re.compile(
    r"^\s*(?:[-_]{2,}\s*)?(?:page|第)\s*\d+(?:\s*(?:/|of|共)\s*\d+)?\s*(?:页)?\s*(?:[-_]{2,})?\s*$",
    re.IGNORECASE,
)
EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")
EXCESS_SPACES_RE = re.compile(r"[ \t]{3,}")


def default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}.cleaned{input_path.suffix}")


def clean_markdown_text(text: str) -> str:
    text = text.replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x0c", "\n\n")
    text = CONTROL_CHAR_RE.sub("", text)

    cleaned_lines: list[str] = []
    in_fenced_block = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fenced_block = not in_fenced_block
            cleaned_lines.append(line.rstrip())
            continue
        if not in_fenced_block and PAGE_MARKER_RE.match(stripped):
            continue
        if in_fenced_block:
            cleaned_lines.append(line.rstrip())
            continue
        cleaned_lines.append(EXCESS_SPACES_RE.sub("  ", line).rstrip())

    cleaned = "\n".join(cleaned_lines).strip()
    cleaned = EXCESS_BLANK_LINES_RE.sub("\n\n", cleaned)
    return cleaned + "\n"


def clean_markdown_file(
    input_path: Path,
    *,
    output_path: Path | None = None,
    overwrite: bool = False,
) -> Path:
    input_path = input_path.resolve()
    target_path = input_path if overwrite else (output_path or default_output_path(input_path))
    target_path = target_path.resolve()

    text = input_path.read_text(encoding="utf-8")
    target_path.write_text(clean_markdown_text(text), encoding="utf-8")
    return target_path


def main() -> int:
    parser = argparse.ArgumentParser(description="轻量清洗 Markdown，不修改业务语义")
    parser.add_argument("input", type=Path, help="输入 Markdown 文件")
    parser.add_argument("--output", type=Path, default=None, help="输出文件，默认生成 *.cleaned.md")
    parser.add_argument("--overwrite", action="store_true", help="显式覆盖输入文件")
    args = parser.parse_args()

    if args.output and args.overwrite:
        parser.error("--output 和 --overwrite 不能同时使用")
    output = clean_markdown_file(args.input, output_path=args.output, overwrite=args.overwrite)
    print(output.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
