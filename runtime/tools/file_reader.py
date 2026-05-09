from __future__ import annotations

from pathlib import Path


def read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_existing_files(
    repo_root: Path, relative_paths: list[str]
) -> tuple[dict[str, str], list[str]]:
    loaded: dict[str, str] = {}
    errors: list[str] = []
    for relative_path in relative_paths:
        path = repo_root / relative_path
        if not path.is_file():
            errors.append(f"缺少必需文件: {relative_path}")
            continue
        loaded[relative_path] = read_utf8(path)
    return loaded, errors
