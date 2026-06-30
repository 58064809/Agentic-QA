from __future__ import annotations

import argparse
from pathlib import Path

TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".py",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".csv",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
}

MOJIBAKE_MARKERS = ("鍩", "轰", "簬", "ä¸", "æ–", "�")


def iter_targets(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return [
        item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in TEXT_SUFFIXES
    ]


def inspect_file(path: Path) -> tuple[str, list[str]]:
    notes: list[str] = []
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        notes.append("utf-8-bom")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return "not-utf8", [f"decode-error:{exc.start}"]
    for marker in MOJIBAKE_MARKERS:
        if marker in text:
            notes.append(f"marker:{marker}")
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        notes.append("contains-cjk")
    return "utf-8", notes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan text files for UTF-8 readability and common Chinese mojibake markers."
    )
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    failures = 0
    for root in args.paths:
        for path in iter_targets(root):
            status, notes = inspect_file(path)
            if status != "utf-8" or any(note.startswith("marker:") for note in notes):
                failures += 1
                print(f"{status}\t{path}\t{', '.join(notes) or '-'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
