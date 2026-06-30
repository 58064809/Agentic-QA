from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_local_agent_skill_state_is_not_in_repo():
    assert not (REPO_ROOT / ".atomcode").exists()
    assert not (REPO_ROOT / ".agents" / "skills-disabled").exists()
    assert not (REPO_ROOT / ".agents" / "skills").exists()


def test_project_codex_config_is_kept():
    assert (REPO_ROOT / ".codex" / "config.toml").is_file()
