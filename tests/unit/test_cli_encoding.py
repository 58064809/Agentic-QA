from __future__ import annotations

from pathlib import Path


def test_cli_sources_do_not_contain_mojibake_error_marker():
    repo_root = Path(__file__).resolve().parents[2]

    for path in (repo_root / "runtime" / "cli").glob("*.py"):
        assert "鉂?" not in path.read_text(encoding="utf-8")
