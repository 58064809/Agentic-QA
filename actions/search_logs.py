from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", ".idea", ".deepeval"}


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _resolve_candidates(file_path: str, root: Path) -> list[Path]:
    if file_path:
        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        return [candidate]

    candidates: list[Path] = []
    for path in root.rglob("*.log"):
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        candidates.append(path)
    return candidates


def search_logs(file_path: str = "", keyword: str = "error", limit: int = 50, workspace_root: str = "") -> dict[str, Any]:
    root = Path(workspace_root) if workspace_root else ROOT
    candidates = _resolve_candidates(file_path, root)
    if file_path and not candidates[0].exists():
        return {
            "task": "log_analysis",
            "file_path": str(candidates[0]),
            "keyword": keyword,
            "match_count": 0,
            "searched_files": 0,
            "matches": [],
            "error": f"log file not found: {candidates[0]}",
        }

    if not candidates:
        return {
            "task": "log_analysis",
            "file_path": file_path,
            "keyword": keyword,
            "match_count": 0,
            "searched_files": 0,
            "matches": [],
            "error": "no_log_files_found",
        }

    matches: list[str] = []
    normalized_keyword = keyword.lower()

    for path in candidates:
        if not path.exists():
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
            if normalized_keyword in line.lower():
                matches.append(f"{_display_path(path, root)}:{line_number}: {line.strip()}")
                if len(matches) >= limit:
                    return {
                        "task": "log_analysis",
                        "file_path": file_path or "",
                        "keyword": keyword,
                        "match_count": len(matches),
                        "searched_files": len(candidates),
                        "matches": matches,
                    }

    return {
        "task": "log_analysis",
        "file_path": file_path or "",
        "keyword": keyword,
        "match_count": len(matches),
        "searched_files": len(candidates),
        "matches": matches,
    }
