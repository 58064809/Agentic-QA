from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _read_markdown(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_markdown_resource(relative_path: str) -> dict[str, Any]:
    path = ROOT / relative_path
    if not path.exists():
        return {
            "path": relative_path,
            "loaded": False,
            "title": path.name,
            "content": "",
        }

    content = _read_markdown(path)
    title = path.stem
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            break

    return {
        "path": relative_path,
        "loaded": True,
        "title": title,
        "content": content,
    }


def summarize_resource(resource: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": resource["path"],
        "loaded": resource["loaded"],
        "title": resource["title"],
    }
