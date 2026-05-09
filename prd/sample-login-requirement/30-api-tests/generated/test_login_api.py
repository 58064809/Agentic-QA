"""Pytest API draft for sample-login-requirement.

AI draft only. It skips by default unless LOGIN_API_BASE_URL is provided.
Do not point LOGIN_API_BASE_URL to production.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

BASE_URL = os.getenv("LOGIN_API_BASE_URL")
pytestmark = pytest.mark.skipif(
    not BASE_URL,
    reason="LOGIN_API_BASE_URL is not set; skip draft API tests by default.",
)


def _post_json(path: str, payload: dict[str, str]) -> tuple[int, dict[str, object]]:
    assert BASE_URL is not None
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            return response.status, data
    except urllib.error.HTTPError as exc:
        data = json.loads(exc.read().decode("utf-8"))
        return exc.code, data


def test_login_success_returns_token_contract() -> None:
    phone = os.getenv("LOGIN_TEST_PHONE")
    password = os.getenv("LOGIN_TEST_PASSWORD")
    if not phone or not password:
        pytest.skip("LOGIN_TEST_PHONE or LOGIN_TEST_PASSWORD is not set.")

    status, data = _post_json("/api/v1/auth/login", {"phone": phone, "password": password})

    assert status in {200, 201}
    assert data.get("code") in {"OK", "SUCCESS", 0}
    payload = data.get("data")
    assert isinstance(payload, dict)
    assert payload.get("access_token")
    assert payload.get("token_type") in {"Bearer", "bearer"}
    assert isinstance(payload.get("expires_in"), int)


def test_login_wrong_password_rejects_without_token() -> None:
    phone = os.getenv("LOGIN_TEST_PHONE")
    wrong_password = os.getenv("LOGIN_WRONG_PASSWORD", "wrong-password")
    if not phone:
        pytest.skip("LOGIN_TEST_PHONE is not set.")

    status, data = _post_json(
        "/api/v1/auth/login",
        {"phone": phone, "password": wrong_password},
    )

    assert status in {200, 400, 401}
    assert data.get("code") in {"INVALID_CREDENTIALS", "AUTH_FAILED", 401}
    assert "token" not in json.dumps(data).lower()
