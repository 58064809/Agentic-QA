from __future__ import annotations

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from harness import (
    ExecutionProfile,
    LoginApiAuthentication,
    StaticTokenApiAuthentication,
)
from harness.domain.models import ExecutionEnvironmentPolicy
from harness.domain.schemas.api_test_cases import ApiTestCase
from harness.domain.schemas.execution_evidence import ExecutionEvidence
from harness.infrastructure.tools.api_execution import execute_api_cases


class FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


@contextmanager
def _authenticated_api_server():
    requests_seen: list[tuple[str, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests_seen.append((self.path, self.headers.get("Authorization")))
            if self.path != "/api/login":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length") or 0)
            credentials = json.loads(self.rfile.read(length))
            if credentials != {"username": "qa-user", "password": "qa-password"}:
                self.send_response(401)
                self.end_headers()
                return
            body = json.dumps({"data": {"access_token": "local-runtime-token"}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            authorization = self.headers.get("Authorization")
            requests_seen.append((self.path, authorization))
            if self.path != "/api/api-local" or authorization != "Bearer local-runtime-token":
                self.send_response(401)
                self.end_headers()
                return
            body = json.dumps({"code": 0}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests_seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _case(case_id: str, method: str, expected: int = 200) -> ApiTestCase:
    return ApiTestCase.model_validate(
        {
            "id": case_id,
            "title": f"case {case_id}",
            "priority": "P1",
            "contract_status": "confirmed",
            "business_rule_refs": ["rule-1"],
            "review_status": "needs_human_review",
            "review_questions": ["environment"],
            "source_refs": [
                {
                    "source_type": "openapi",
                    "source_path": "sources/openapi.json",
                    "chunk_id": "openapi.demo.GET.1",
                    "locator": f"{method} /api/{case_id.lower()}",
                    "summary": "recorded contract",
                    "confidence": "high",
                }
            ],
            "pending": [],
            "request": {"method": method, "path": f"/api/{case_id.lower()}"},
            "assertions": [
                {"type": "status_code", "expected": [expected]},
                {"type": "json_field_exists", "path": "$.code"},
            ],
            "variables": {},
            "cleanup": [],
        }
    )


def test_execution_records_pass_failure_and_policy_block() -> None:
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        status = 200 if url.endswith("api-001") else 500
        return FakeResponse(status, {"code": 0})

    evidence = execute_api_cases(
        [_case("API-001", "GET"), _case("API-002", "GET"), _case("API-003", "POST")],
        run_id="run-test",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="staging",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://secret.example.test"},
        request_func=request,
    )

    assert evidence.summary.model_dump() == {
        "total": 3,
        "executed": 2,
        "passed": 1,
        "failed": 1,
        "errors": 0,
        "blocked": 1,
    }
    assert [item.status for item in evidence.cases] == ["passed", "failed", "blocked"]
    assert len(calls) == 2
    assert "secret.example.test" not in evidence.model_dump_json()


def test_execution_error_redacts_url_and_environment_secret() -> None:
    def request(method, url, **kwargs):
        raise RuntimeError(f"request failed for {url} token-secret")

    evidence = execute_api_cases(
        [_case("API-001", "GET")],
        run_id="run-test",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="staging",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://secret.example.test", "TOKEN": "token-secret"},
        request_func=request,
    )

    assert evidence.cases[0].status == "error"
    assert evidence.cases[0].error == "request failed for <redacted-url> <redacted>"


def test_execution_evidence_rejects_inconsistent_summary() -> None:
    evidence = execute_api_cases(
        [_case("API-001", "GET")],
        run_id="run-test",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="staging",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=lambda *_args, **_kwargs: FakeResponse(200, {"code": 0}),
    ).model_dump(mode="json")
    evidence["summary"]["passed"] = 0

    with pytest.raises(ValueError, match="does not match cases"):
        ExecutionEvidence.model_validate(evidence)


def test_execution_blocks_unconfirmed_case_without_sending_request() -> None:
    case = _case("API-PENDING", "GET").model_copy(
        update={
            "contract_status": "pending_confirmation",
            "request": _case("API-PENDING-REQUEST", "GET").request.model_copy(
                update={"method": None, "path": None}
            ),
        }
    )
    calls = []

    evidence = execute_api_cases(
        [case],
        run_id="run-test",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="staging",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=lambda *_args, **_kwargs: calls.append(True),
    )

    assert evidence.summary.blocked == 1
    assert evidence.cases[0].error == "API contract is not confirmed"
    assert calls == []


def test_static_token_authentication_injects_configured_header_once_per_case() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse(200, {"code": 0})

    case = _case("API-STATIC", "GET")
    case.request.headers["authorization"] = "stale-value"
    evidence = execute_api_cases(
        [case],
        run_id="run-static",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={
            "TEST_BASE_URL": "https://example.test",
            "QA_API_TOKEN": "runtime-static-token",
        },
        authentication=StaticTokenApiAuthentication(
            mode="static_token",
            token_env="QA_API_TOKEN",
        ),
        request_func=request,
    )

    assert evidence.summary.passed == 1
    assert calls[0][2]["headers"] == {"Authorization": "Bearer runtime-static-token"}
    assert "runtime-static-token" not in evidence.model_dump_json()


def test_direct_static_token_is_masked_in_config_model_and_used_at_runtime() -> None:
    calls: list[dict[str, object]] = []
    authentication = StaticTokenApiAuthentication(
        mode="static_token",
        token="direct-runtime-token",
    )

    evidence = execute_api_cases(
        [_case("API-DIRECT", "GET")],
        run_id="run-direct",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        authentication=authentication,
        request_func=lambda _method, _url, **kwargs: (
            calls.append(kwargs) or FakeResponse(200, {"code": 0})
        ),
    )

    assert evidence.summary.passed == 1
    assert calls[0]["headers"] == {"Authorization": "Bearer direct-runtime-token"}
    assert "direct-runtime-token" not in authentication.model_dump_json()
    assert "direct-runtime-token" not in evidence.model_dump_json()


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "static_token"},
        {
            "mode": "static_token",
            "token": "direct-runtime-token",
            "token_env": "QA_API_TOKEN",
        },
    ],
)
def test_static_token_config_requires_exactly_one_source(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        StaticTokenApiAuthentication.model_validate(payload)


def test_login_authentication_fetches_token_once_then_injects_it_into_cases() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/api/login"):
            assert kwargs["json"] == {"username": "qa-user", "password": "qa-password"}
            return FakeResponse(200, {"data": {"access_token": "login-runtime-token"}})
        return FakeResponse(200, {"code": 0})

    authentication = LoginApiAuthentication.model_validate(
        {
            "mode": "login",
            "request": {
                "method": "POST",
                "path": "/api/login",
                "body": {
                    "username": "${QA_API_USER}",
                    "password": "${QA_API_PASSWORD}",
                },
            },
            "token_json_path": "$.data.access_token",
            "expected_status_codes": [200, 201],
            "injection": {
                "location": "header",
                "name": "X-Access-Token",
                "prefix": "",
            },
        }
    )
    evidence = execute_api_cases(
        [_case("API-LOGIN-1", "GET"), _case("API-LOGIN-2", "GET")],
        run_id="run-login",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET", "POST"],
        ),
        env={
            "TEST_BASE_URL": "https://example.test",
            "QA_API_USER": "qa-user",
            "QA_API_PASSWORD": "qa-password",
        },
        authentication=authentication,
        request_func=request,
    )

    assert evidence.summary.passed == 2
    assert [item[0] for item in calls] == ["POST", "GET", "GET"]
    assert calls[1][2]["headers"] == {"X-Access-Token": "login-runtime-token"}
    assert calls[2][2]["headers"] == {"X-Access-Token": "login-runtime-token"}
    assert "login-runtime-token" not in evidence.model_dump_json()


def test_login_authentication_real_http_smoke() -> None:
    authentication = LoginApiAuthentication.model_validate(
        {
            "mode": "login",
            "request": {
                "path": "/api/login",
                "body": {
                    "username": "${QA_API_USER}",
                    "password": "${QA_API_PASSWORD}",
                },
            },
            "token_json_path": "$.data.access_token",
        }
    )

    with _authenticated_api_server() as (base_url, requests_seen):
        evidence = execute_api_cases(
            [_case("API-LOCAL", "GET")],
            run_id="run-local-http",
            source_cases_path="published/api_test_draft/current.yml",
            profile=ExecutionProfile(
                environment="local-test",
                base_url_env="TEST_BASE_URL",
                allowed_http_methods=["GET", "POST"],
            ),
            env={
                "TEST_BASE_URL": base_url,
                "QA_API_USER": "qa-user",
                "QA_API_PASSWORD": "qa-password",
            },
            authentication=authentication,
        )

    assert evidence.summary.passed == 1
    assert requests_seen == [
        ("/api/login", None),
        ("/api/api-local", "Bearer local-runtime-token"),
    ]
    assert "local-runtime-token" not in evidence.model_dump_json()


def test_authentication_reports_missing_environment_names_without_sending_request() -> None:
    calls: list[bool] = []
    authentication = LoginApiAuthentication.model_validate(
        {
            "mode": "login",
            "request": {
                "path": "/api/login",
                "body": {"password": "${QA_API_PASSWORD}"},
            },
            "token_json_path": "$.token",
        }
    )

    with pytest.raises(RuntimeError, match="QA_API_PASSWORD"):
        execute_api_cases(
            [_case("API-LOGIN", "GET")],
            run_id="run-login",
            source_cases_path="published/api_test_draft/current.yml",
            profile=ExecutionProfile(
                environment="qa",
                base_url_env="TEST_BASE_URL",
                allowed_http_methods=["GET", "POST"],
            ),
            env={"TEST_BASE_URL": "https://example.test"},
            authentication=authentication,
            request_func=lambda *_args, **_kwargs: calls.append(True),
        )

    assert calls == []


def test_login_authentication_respects_execution_method_allowlist() -> None:
    authentication = LoginApiAuthentication.model_validate(
        {
            "mode": "login",
            "request": {"path": "/api/login"},
            "token_json_path": "$.token",
        }
    )

    with pytest.raises(PermissionError, match="POST"):
        execute_api_cases(
            [_case("API-LOGIN", "GET")],
            run_id="run-login",
            source_cases_path="published/api_test_draft/current.yml",
            profile=ExecutionProfile(
                environment="qa",
                base_url_env="TEST_BASE_URL",
                allowed_http_methods=["GET"],
            ),
            env={"TEST_BASE_URL": "https://example.test"},
            authentication=authentication,
            request_func=lambda *_args, **_kwargs: pytest.fail("request should not be sent"),
        )


def test_login_failure_does_not_expose_credentials_or_response_token() -> None:
    authentication = LoginApiAuthentication.model_validate(
        {
            "mode": "login",
            "request": {
                "path": "/api/login",
                "body": {"password": "${QA_API_PASSWORD}"},
            },
            "token_json_path": "$.token",
        }
    )

    with pytest.raises(RuntimeError) as captured:
        execute_api_cases(
            [_case("API-LOGIN", "GET")],
            run_id="run-login",
            source_cases_path="published/api_test_draft/current.yml",
            profile=ExecutionProfile(
                environment="qa",
                base_url_env="TEST_BASE_URL",
                allowed_http_methods=["GET", "POST"],
            ),
            env={
                "TEST_BASE_URL": "https://example.test",
                "QA_API_PASSWORD": "runtime-password",
            },
            authentication=authentication,
            request_func=lambda *_args, **_kwargs: FakeResponse(
                200, {"token": {"raw": "runtime-response-token"}}
            ),
        )

    error = str(captured.value)
    assert "runtime-password" not in error
    assert "runtime-response-token" not in error


@pytest.mark.parametrize(
    "login_request",
    [
        {"path": "/api/login", "body": {"password": "inline-password"}},
        {"path": "/api/login", "headers": {"Authorization": "Bearer inline-token"}},
        {"path": "/api/login", "headers": {"Host": "outside.example"}},
        {"path": "/api/login?next=/outside"},
        {"path": "/api/login", "headers": {"X-Test": "value\r\nInjected: true"}},
    ],
)
def test_login_config_rejects_inline_sensitive_values_and_transport_headers(
    login_request: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        LoginApiAuthentication.model_validate(
            {
                "mode": "login",
                "request": login_request,
                "token_json_path": "$.token",
            }
        )


def test_workspace_execution_policy_parses_static_and_login_authentication() -> None:
    static = ExecutionEnvironmentPolicy.model_validate(
        {
            "base_url_env": "TEST_BASE_URL",
            "api_auth": {
                "mode": "static_token",
                "token_env": "QA_API_TOKEN",
            },
        }
    )
    login = ExecutionEnvironmentPolicy.model_validate(
        {
            "base_url_env": "TEST_BASE_URL",
            "api_auth": {
                "mode": "login",
                "request": {
                    "path": "/api/login",
                    "body": {"password": "${QA_API_PASSWORD}"},
                },
                "token_json_path": "$.data.token",
            },
        }
    )

    assert isinstance(static.api_auth, StaticTokenApiAuthentication)
    assert isinstance(login.api_auth, LoginApiAuthentication)
