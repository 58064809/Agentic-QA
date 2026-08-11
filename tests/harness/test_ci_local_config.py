from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from harness.infrastructure.local_config import FilesystemLocalConfigLoader


def test_ci_bootstrap_only_populates_secret_provider_storage(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    (tmp_path / "agentic-qa.local.example.yml").write_text(
        (repo_root / "agentic-qa.local.example.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "local-sources" / "api" / "member-service").mkdir(parents=True)
    loader = FilesystemLocalConfigLoader(tmp_path)
    loader.init()

    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "configure-ci-local.py"),
            "--profile",
            "ci",
            "--config",
            str(loader.path),
        ],
        check=True,
    )

    raw = yaml.safe_load(loader.path.read_text(encoding="utf-8"))
    assert raw["postgres"]["password"] == "secret://postgres.password"
    assert raw["runtime"]["cleanup_journal_key"] == ("secret://runtime.cleanup_journal_key")
    assert raw["secrets"]["values"]["postgres.password"] == "postgres"
    assert loader.check().ready is True


def test_workflows_do_not_replace_secret_bearing_business_fields() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    paths = [
        repo_root / ".github" / "workflows" / "ci.yml",
        repo_root / ".github" / "workflows" / "nightly-live-eval.yml",
    ]
    forbidden = (
        "d['postgres']['password']",
        'd["postgres"]["password"]',
        "d['runtime']['cleanup_journal_key']",
        'd["runtime"]["cleanup_journal_key"]',
    )
    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert not any(item in content for item in forbidden), path
