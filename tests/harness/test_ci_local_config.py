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
    assert raw["system_database"]["password"] == "secret://system_database.password"
    assert raw["runtime"]["cleanup_journal_key"] == ("secret://runtime.cleanup_journal_key")
    assert raw["secrets"]["values"]["system_database.password"] == "postgres"
    assert (tmp_path / "local-sources" / "api" / "member-service").is_dir()
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


def test_ci_has_matrix_pip_check_and_independent_cold_start() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    ci = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    nightly = (repo_root / ".github" / "workflows" / "nightly-live-eval.yml").read_text(
        encoding="utf-8"
    )

    assert 'python-version: ["3.10", "3.11", "3.12"]' in ci
    assert ci.count("python -m pip check") >= 1
    assert "cold-start:" in ci
    assert ".fresh-venv/bin/python -m pip check" in ci
    assert ".fresh-venv/bin/python scripts/configure-ci-local.py --profile ci" in ci
    assert "python -m pip check" in nightly
    assert "python scripts/configure-ci-local.py --profile nightly" in nightly
    assert nightly.count("DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}") == 2
    assert nightly.count("environment: nightly-live-eval") == 2
