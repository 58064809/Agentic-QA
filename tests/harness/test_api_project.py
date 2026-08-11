from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
import yaml

from harness import ApiProjectCheckCommand, Harness
from harness.application.qa_design import TESTCASE_HEADERS
from harness.infrastructure.api_project import FilesystemApiProjectChecker
from harness.infrastructure.local_config import FilesystemLocalConfigLoader


def _openapi(*, endpoint_count: int = 1) -> dict[str, object]:
    paths: dict[str, object] = {
        f"/items/{index}": {
            "get": {"summary": f"item {index}", "responses": {"200": {"description": "ok"}}}
        }
        for index in range(endpoint_count)
    }
    paths["/member/app/login/phoneLogin"] = {
        "post": {
            "summary": "phone login",
            "responses": {"200": {"description": "ok"}},
        }
    }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Member", "version": "1"},
        "paths": paths,
    }


def _manual_csv() -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(TESTCASE_HEADERS)
    writer.writerow(
        [
            "TC-LOGIN-001",
            "LOGIN-001",
            "phone login",
            "API",
            "P1",
            "dev environment",
            "QA phone",
            "POST /member/app/login/phoneLogin",
            "login succeeds",
            "status_code equals 200",
            "do not persist tokens",
        ]
    )
    return output.getvalue()


def _write_sources(repo: Path, *, endpoint_count: int = 1) -> Path:
    source = repo / "local-sources" / "api" / "member-service"
    source.mkdir(parents=True)
    (source / "member-service.json").write_text(
        json.dumps(_openapi(endpoint_count=endpoint_count)), encoding="utf-8"
    )
    (source / "test-cases.csv").write_text(_manual_csv(), encoding="utf-8")
    return source


def _login(
    *,
    tel_code: str = "+86",
    phone: str = "13800000000",
    sms_code: str = "000000",
    key: str = "unit-test-key-16",
) -> dict[str, object]:
    return {
        "kind": "sms",
        "request_path": "/member/app/login/phoneLogin",
        "tel_code": tel_code,
        "phone": phone,
        "sms_code": sms_code,
        "request_headers": {"Accept": "application/json"},
        "null_body_fields": ["inviteCode", "imageCode", "registrationId"],
        "token_json_path": "$.data.userInfo.accessToken",
        "injection": {"name": "accesstoken", "prefix": ""},
        "encryption": {
            "algorithm": "aes-128-cbc-pkcs7-base64-iv-prefix",
            "key": key,
            "fields": ["phone", "smsCode"],
        },
        "success_condition": {"json_path": "$.code", "expected": 1000},
    }


def _payload(
    source: Path,
    *,
    environment: str = "dev",
    base_url: str = "https://member.example.test/api",
    login: dict[str, object] | None = None,
    fallback_token: str = "",
) -> dict[str, object]:
    auth: dict[str, object] = {"fallback_token": fallback_token}
    if login is not None:
        auth["login"] = login
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
            "password": "unit-only",
        },
        "test_management": {"provider": "none"},
        "workspace_defaults": {},
        "api": {
            "services": {
                "member-service": {
                    "source_directory": source.relative_to(source.parents[2]).as_posix(),
                    "environments": {
                        environment: {
                            "base_url": base_url,
                            "trusted_origins": ["https://member.example.test"],
                            "allowed_http_methods": ["GET", "POST"],
                            "auth": auth,
                        }
                    },
                }
            }
        },
    }


def _write_config(repo: Path, payload: dict[str, object]) -> None:
    (repo / "agentic-qa.local.yml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    FilesystemLocalConfigLoader(repo).migrate_inline_secrets()


def _check(repo: Path, source: Path, environment: str = "dev"):
    return FilesystemApiProjectChecker(repo).check(
        ApiProjectCheckCommand(source_directory=str(source), environment=environment)
    )


def test_doctor_resolves_sms_login_without_exposing_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNIT_MODEL_KEY", "model-key")
    source = _write_sources(tmp_path)
    _write_config(tmp_path, _payload(source, login=_login(), fallback_token="unused-token"))

    result = _check(tmp_path, source)

    assert result.ready
    assert result.config_path == str(tmp_path / "agentic-qa.local.yml")
    assert result.selected_authentication == "sms"
    serialized = result.model_dump_json()
    for secret in ("13800000000", "unit-test-key-16", "unused-token"):
        assert secret not in serialized
    assert result.execution_policy is not None
    assert result.execution_policy.base_url_env == "LOCAL_MEMBER_SERVICE_DEV_BASE_URL"
    authentication = result.execution_policy.api_auth
    assert authentication is not None and authentication.mode == "login"
    assert authentication.request_encryption is not None


def test_empty_login_uses_direct_fallback_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNIT_MODEL_KEY", "model-key")
    source = _write_sources(tmp_path)
    _write_config(
        tmp_path,
        _payload(
            source,
            login=_login(tel_code="", phone="", sms_code="", key=""),
            fallback_token="token",
        ),
    )
    result = _check(tmp_path, source)
    assert result.ready
    assert result.selected_authentication == "static_token"


def test_password_login_carries_confirmed_request_encryption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNIT_MODEL_KEY", "model-key")
    source = _write_sources(tmp_path)
    login = {
        "kind": "password",
        "request_path": "/member/app/login/passwordLogin",
        "username": "qa-user",
        "password": "qa-password",
        "token_json_path": "$.data.accessToken",
        "encryption": {
            "algorithm": "aes-128-cbc-pkcs7-base64-iv-prefix",
            "key": "unit-test-key-16",
            "fields": ["password"],
        },
    }
    _write_config(tmp_path, _payload(source, login=login))

    result = _check(tmp_path, source)

    assert result.ready
    assert result.selected_authentication == "password"
    authentication = result.execution_policy.api_auth if result.execution_policy else None
    assert authentication is not None and authentication.mode == "login"
    assert authentication.request_encryption is not None


@pytest.mark.parametrize(
    ("login", "code"),
    [
        (_login(phone=""), "API_LOGIN_CREDENTIAL_PARTIAL"),
        (_login(sms_code="123456"), "API_SMS_CODE_INVALID_FOR_ENV"),
        (_login(key="short"), "API_LOGIN_ENCRYPTION_KEY_INVALID"),
    ],
)
def test_doctor_rejects_invalid_login(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    login: dict[str, object],
    code: str,
) -> None:
    monkeypatch.setenv("UNIT_MODEL_KEY", "model-key")
    source = _write_sources(tmp_path)
    _write_config(tmp_path, _payload(source, login=login, fallback_token="cannot-mask-partial"))
    result = _check(tmp_path, source)
    assert not result.ready
    assert code in {item.code for item in result.issues}


def test_production_and_source_directory_drift_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNIT_MODEL_KEY", "model-key")
    source = _write_sources(tmp_path)
    _write_config(tmp_path, _payload(source, environment="production", login=_login()))
    production = _check(tmp_path, source, "production")
    assert "API_PRODUCTION_UNSUPPORTED" in {item.code for item in production.issues}

    other = tmp_path / "other"
    other.mkdir()
    drift = _check(tmp_path, other, "production")
    assert "API_PROJECT_NOT_CONFIGURED" in {item.code for item in drift.issues}


def test_legacy_service_config_is_an_explicit_migration_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNIT_MODEL_KEY", "model-key")
    source = _write_sources(tmp_path)
    _write_config(tmp_path, _payload(source, login=_login()))
    (source / "api-test.yml").write_text("legacy: true\n", encoding="utf-8")
    result = _check(tmp_path, source)
    assert "API_LEGACY_CONFIG_PRESENT" in {item.code for item in result.issues}


def test_missing_and_direct_model_key_configuration_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNIT_MODEL_KEY", "model-key")
    source = _write_sources(tmp_path)
    missing = _check(tmp_path, source)
    assert "LOCAL_CONFIG_MISSING" in {item.code for item in missing.issues}

    payload = _payload(source, login=_login())
    payload["model"]["api_key"] = "must-not-be-in-file"  # type: ignore[index]
    _write_config(tmp_path, payload)
    checked = FilesystemLocalConfigLoader(tmp_path).check()
    assert not checked.ready
    assert checked.issues[0].code == "LOCAL_CONFIG_INVALID"


def test_large_openapi_is_fully_inspected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIT_MODEL_KEY", "model-key")
    source = _write_sources(tmp_path, endpoint_count=1800)
    assert (source / "member-service.json").stat().st_size > 100_000
    _write_config(tmp_path, _payload(source, login=_login()))
    assert _check(tmp_path, source).ready


def test_public_harness_exposes_local_config_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNIT_MODEL_KEY", "model-key")
    source = _write_sources(tmp_path)
    _write_config(tmp_path, _payload(source, login=_login()))
    assert Harness(tmp_path).check_local_config().ready
