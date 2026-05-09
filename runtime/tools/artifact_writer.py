from __future__ import annotations

from pathlib import Path


def ensure_within_directory(path: Path, directory: Path) -> bool:
    resolved_path = path.resolve()
    resolved_directory = directory.resolve()
    return resolved_path == resolved_directory or resolved_directory in resolved_path.parents


def write_new_text(path: Path, content: str) -> None:
    if path.exists():
        raise FileExistsError(f"目标文件已存在，默认不覆盖: {path.as_posix()}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
