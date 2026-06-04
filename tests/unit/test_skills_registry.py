from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_required_first_version_skills_registry_is_complete():
    registry_path = REPO_ROOT / "skills" / "registry" / "skills.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))

    skills = registry["skills"]
    assert registry["required_first_version"] is True
    assert len(skills) == 10
    assert {skill["id"] for skill in skills} == {f"S{index}" for index in range(1, 11)}

    for skill in skills:
        assert skill["required_first_version"] is True
        assert skill["priority"] == int(skill["id"].removeprefix("S"))
        assert skill["file"].startswith("skills/")
        assert (REPO_ROOT / skill["file"]).is_file()
