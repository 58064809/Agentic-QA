from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest
import yaml

from harness.infrastructure.local_config import FilesystemLocalConfigLoader


def _legacy_payload() -> dict[str, object]:
    return {
        "schema_version": "agentic-qa.local-config.v1",
        "model": {
            "provider": "recorded",
            "api_key_env": "UNIT_MODEL_KEY",
            "flash_model": "recorded-flash",
            "pro_model": "recorded-pro",
            "base_url": "https://model.example.test",
        },
        "rag": {"provider": "local-lexical"},
        "postgres": {
            "host": "localhost",
            "port": 5432,
            "database": "postgres",
            "user": "postgres",
            "password": "database-secret",
        },
        "test_management": {"provider": "none"},
        "workspace_defaults": {},
        "runtime": {"cleanup_journal_key": base64.urlsafe_b64encode(b"x" * 32).decode("ascii")},
        "api": {
            "services": {
                "orders": {
                    "source_directory": "local-sources/api/orders",
                    "environments": {
                        "qa": {
                            "base_url": "https://qa.example.test",
                            "trusted_origins": ["https://qa.example.test"],
                            "allowed_http_methods": ["GET"],
                            "auth": {"fallback_token": "api-secret"},
                        }
                    },
                }
            }
        },
    }


def _write_legacy(repo: Path) -> FilesystemLocalConfigLoader:
    (repo / "local-sources" / "api" / "orders").mkdir(parents=True)
    (repo / "agentic-qa.local.yml").write_text(
        yaml.safe_dump(_legacy_payload(), sort_keys=False), encoding="utf-8"
    )
    return FilesystemLocalConfigLoader(repo)


def test_inline_secret_migration_replaces_fields_and_resolves_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("UNIT_MODEL_KEY", "model-key")
    loader = _write_legacy(tmp_path)

    loader.migrate_inline_secrets()

    persisted = yaml.safe_load(loader.path.read_text(encoding="utf-8"))
    assert list(persisted)[:2] == ["schema_version", "secrets"]
    assert persisted["postgres"]["password"] == "secret://postgres.password"
    assert (
        persisted["api"]["services"]["orders"]["environments"]["qa"]["auth"]["fallback_token"]
        == "secret://api.orders.qa.auth.fallback_token"
    )
    assert persisted["runtime"]["cleanup_journal_key"] == ("secret://runtime.cleanup_journal_key")
    loaded = loader.load_required()
    assert loaded.postgres.password == "database-secret"
    assert loaded.runtime.cleanup_journal_key
    assert loaded.api.services["orders"].environments["qa"].auth.fallback_token == ("api-secret")
    with pytest.raises(FileExistsError, match="already declares"):
        loader.migrate_inline_secrets()


def test_environment_secret_provider_keeps_values_out_of_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("UNIT_MODEL_KEY", "model-key")
    loader = _write_legacy(tmp_path)
    loader.migrate_inline_secrets()
    payload = yaml.safe_load(loader.path.read_text(encoding="utf-8"))
    references = list(payload["secrets"]["values"])
    payload["secrets"] = {
        "provider": "environment",
        "variables": {
            reference: f"UNIT_SECRET_{index}" for index, reference in enumerate(references)
        },
    }
    for index, reference in enumerate(references):
        value = {
            "postgres.password": "database-secret",
            "runtime.cleanup_journal_key": base64.urlsafe_b64encode(b"y" * 32).decode("ascii"),
            "api.orders.qa.auth.fallback_token": "api-secret",
        }[reference]
        monkeypatch.setenv(f"UNIT_SECRET_{index}", value)
    loader.path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    loaded = loader.load_required()

    assert loaded.secrets.provider == "environment"
    assert loaded.postgres.password == "database-secret"
    serialized = loader.path.read_text(encoding="utf-8")
    assert "database-secret" not in serialized
    assert "api-secret" not in serialized


def test_secret_provider_is_required_and_references_are_location_scoped(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("UNIT_MODEL_KEY", "model-key")
    loader = _write_legacy(tmp_path)
    missing_provider = loader.check()
    assert missing_provider.ready is False
    assert {issue.code for issue in missing_provider.issues} == {"LOCAL_SECRET_PROVIDER_INVALID"}

    loader.migrate_inline_secrets()
    payload = yaml.safe_load(loader.path.read_text(encoding="utf-8"))
    payload["model"]["flash_model"] = "secret://postgres.password"
    loader.path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    unexpected_reference = loader.check()
    assert unexpected_reference.ready is False
    assert unexpected_reference.issues[0].code == "LOCAL_SECRET_PROVIDER_INVALID"
    assert "model.flash_model" in unexpected_reference.issues[0].message


def test_config_init_generates_runtime_key_in_local_provider(tmp_path: Path) -> None:
    (tmp_path / "agentic-qa.local.example.yml").write_text(
        "schema_version: agentic-qa.local-config.v1\n"
        "secrets:\n"
        "  provider: local\n"
        "  values:\n"
        "    runtime.cleanup_journal_key: ''\n"
        "runtime:\n"
        "  cleanup_journal_key: secret://runtime.cleanup_journal_key\n",
        encoding="utf-8",
    )

    target = FilesystemLocalConfigLoader(tmp_path).init()
    payload = yaml.safe_load(target.read_text(encoding="utf-8"))

    assert payload["runtime"]["cleanup_journal_key"] == ("secret://runtime.cleanup_journal_key")
    encoded_key = payload["secrets"]["values"]["runtime.cleanup_journal_key"]
    assert len(base64.urlsafe_b64decode(encoded_key)) == 32
    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission contract")
def test_config_doctor_rejects_group_or_other_permissions(tmp_path: Path) -> None:
    loader = _write_legacy(tmp_path)
    loader.migrate_inline_secrets()
    os.chmod(loader.path, 0o644)

    result = loader.check()

    assert result.ready is False
    assert result.issues[0].code == "LOCAL_CONFIG_PERMISSION_TOO_OPEN"
    assert "chmod 600" in result.issues[0].remediation
