from __future__ import annotations

import base64
import hashlib
import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from harness import (
    ExecutionProfile,
    LoginApiAuthentication,
    StaticTokenApiAuthentication,
)
from harness.domain.models import (
    ApiIsolationPolicy,
    ApiNamespaceInjection,
    ApiOperationPolicy,
    ExecutionEnvironmentPolicy,
)
from harness.domain.schemas.api_test_cases import (
    ApiTestCase,
    api_case_runtime_definition_errors,
    validate_api_cleanup_policy,
)
from harness.domain.schemas.execution_evidence import ExecutionEvidence
from harness.infrastructure.tools import api_execution as execution_module
from harness.infrastructure.tools.api_execution import execute_api_cases


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        body: object | None = None,
        *,
        headers: dict[str, str] | None = None,
        url: str | None = None,
    ) -> None:
        self.status_code = status_code
        self._body = {} if body is None else body
        self.headers = headers or {}
        self.url = url

    def json(self):
        return self._body


def _decrypt_login_fixture(value: str, key: str) -> str:
    combined = base64.b64decode(value, validate=True)
    decryptor = Cipher(
        algorithms.AES(key.encode("utf-8")),
        modes.CBC(combined[:16]),
    ).decryptor()
    padded = decryptor.update(combined[16:]) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")


@contextmanager
def _authenticated_api_server():
    requests_seen: list[tuple[str, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            requests_seen.append((self.path, self.headers.get("Authorization")))
            if self.path != "/api/login":
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length") or 0)
            credentials = json.loads(self.rfile.read(length))
            if credentials != {"username": "qa-user", "password": "qa-password"}:
                self.send_response(401)
                self.send_header("Content-Length", "0")
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
                self.send_header("Content-Length", "0")
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


@contextmanager
def _encrypted_member_api_server():
    fixture_key = "test-key-16-byte"
    requests_seen: list[tuple[str, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            requests_seen.append((self.path, self.headers.get("accesstoken")))
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length))
            valid = (
                self.path == "/member/app/login/phoneLogin"
                and self.headers.get("Accept") == "application/json"
                and payload.get("telCode") == "+86"
                and _decrypt_login_fixture(payload.get("phone", ""), fixture_key) == "fixture-phone"
                and _decrypt_login_fixture(payload.get("smsCode", ""), fixture_key) == "000000"
                and payload.get("inviteCode") is None
                and payload.get("imageCode") is None
                and payload.get("registrationId") is None
            )
            response = (
                {
                    "code": 1000,
                    "data": {"userInfo": {"accessToken": "local-member-token"}},
                }
                if valid
                else {"code": 1001}
            )
            body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            token = self.headers.get("accesstoken")
            requests_seen.append((self.path, token))
            status = 200 if token == "local-member-token" else 401
            body = json.dumps({"code": 1000 if status == 200 else 1001}).encode()
            self.send_response(status)
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
        yield f"http://127.0.0.1:{server.server_port}", requests_seen, fixture_key
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


def _case_with_assertions(assertions: list[dict[str, object]]) -> ApiTestCase:
    payload = _case("API-ASSERTIONS", "GET").model_dump(mode="python")
    payload["assertions"] = assertions
    return ApiTestCase.model_validate(payload)


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


def test_namespace_and_declared_idempotency_are_injected_without_raw_log_values() -> None:
    calls: list[dict[str, object]] = []
    events: list[tuple[str, dict[str, object]]] = []

    def request(_method, url, **kwargs):
        calls.append(kwargs)
        return FakeResponse(200, {"code": 0}, url=url)

    policy = ApiOperationPolicy(
        classification="mutation_idempotent",
        idempotency_header="Idempotency-Key",
    )
    isolation = ApiIsolationPolicy(
        mode="namespace",
        namespace=ApiNamespaceInjection(location="header", name="X-Test-Namespace"),
    )
    evidence = execute_api_cases(
        [_case("API-IDEMPOTENT", "POST")],
        run_id="execution-stable",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="staging",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["POST"],
        ),
        env={"TEST_BASE_URL": "https://api.example.test"},
        request_func=request,
        isolation=isolation,
        operation_policies={"POST /api/api-idempotent": policy},
        event_callback=lambda event_type, payload: events.append((event_type, payload)),
    )

    assert evidence.cases[0].status == "passed"
    headers = calls[0]["headers"]
    assert isinstance(headers, dict)
    assert str(headers["X-Test-Namespace"]).startswith("aqa-")
    assert str(headers["Idempotency-Key"]).startswith("aqa-")
    event_payload = json.dumps(events, ensure_ascii=False)
    assert str(headers["X-Test-Namespace"]) not in event_payload
    assert str(headers["Idempotency-Key"]) not in event_payload
    assert {event_type for event_type, _payload in events} >= {
        "isolation.applied",
        "idempotency.configured",
        "request.sent",
    }


def test_manual_only_operation_is_blocked_without_transport() -> None:
    calls: list[str] = []
    evidence = execute_api_cases(
        [_case("API-MANUAL", "POST")],
        run_id="execution-manual",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="staging",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["POST"],
        ),
        env={"TEST_BASE_URL": "https://api.example.test"},
        request_func=lambda _method, url, **_kwargs: calls.append(url),
        operation_policies={
            "POST /api/api-manual": ApiOperationPolicy(classification="mutation_manual")
        },
    )

    assert evidence.cases[0].status == "blocked"
    assert calls == []


def test_operation_policy_controls_cleanup_for_nonstandard_method_semantics() -> None:
    post = _case("API-READ-POST", "POST")
    validate_api_cleanup_policy(
        [post],
        (),
        {"POST /api/api-read-post": ApiOperationPolicy(classification="read_only")},
    )

    get = _case("API-MUTATING-GET", "GET")
    with pytest.raises(ValueError, match="requires cleanup"):
        validate_api_cleanup_policy(
            [get],
            (),
            {"GET /api/api-mutating-get": ApiOperationPolicy(classification="mutation_cleanup")},
        )

    with pytest.raises(ValueError, match="manual-only"):
        validate_api_cleanup_policy(
            [post],
            (),
            {"POST /api/api-read-post": ApiOperationPolicy(classification="mutation_manual")},
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "file:///tmp/api",
        "https://user@example.test/api",
        "https://example.test/api?target=outside",
        "https://example.test/api#fragment",
        "https://example.test/api/../admin",
    ],
)
def test_execution_rejects_unsafe_base_url_before_authentication(base_url: str) -> None:
    calls: list[bool] = []

    with pytest.raises(ValueError, match="base URL"):
        execute_api_cases(
            [_case("API-BASE-URL", "GET")],
            run_id="run-base-url",
            source_cases_path="published/api_test_draft/current.yml",
            profile=ExecutionProfile(
                environment="qa",
                base_url_env="TEST_BASE_URL",
                allowed_http_methods=["GET"],
            ),
            env={"TEST_BASE_URL": base_url},
            request_func=lambda *_args, **_kwargs: calls.append(True),
        )

    assert calls == []


@pytest.mark.parametrize(
    "path",
    [
        "/orders/../admin",
        "/orders/%2e%2e/admin",
        "/orders/%252e%252e/admin",
        "/orders\\admin",
    ],
)
def test_execution_rejects_final_path_escape_before_sending(path: str) -> None:
    payload = _case("API-PATH-ESCAPE", "GET").model_dump(mode="python")
    payload["request"]["path"] = path
    calls: list[bool] = []

    evidence = execute_api_cases(
        [ApiTestCase.model_validate(payload)],
        run_id="run-path-escape",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://example.test/api"},
        request_func=lambda *_args, **_kwargs: calls.append(True),
    )

    assert evidence.cases[0].status == "blocked"
    assert calls == []


def test_execution_pins_final_url_path_origin_and_redirect_policy() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def request(_method: str, url: str, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(
            200,
            {"code": 0},
            url="https://outside.test/api/api-final-url",
        )

    evidence = execute_api_cases(
        [_case("API-FINAL-URL", "GET")],
        run_id="run-final-url",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://example.test/api"},
        request_func=request,
    )

    assert calls[0][0] == "https://example.test/api/api/api-final-url"
    assert calls[0][1]["allow_redirects"] is False
    assert evidence.cases[0].status == "error"
    assert "origin" in str(evidence.cases[0].error).lower()


def test_extended_assertions_pass_and_record_only_value_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = iter([0.0, 0.025, 0.026])
    monkeypatch.setattr(execution_module, "perf_counter", lambda: next(times))
    case = _case_with_assertions(
        [
            {
                "type": "json_field_equals",
                "path": "$.data.items[0].name",
                "expected": "alpha",
            },
            {
                "type": "json_field_equals",
                "path": "$.data.optional",
                "expected": None,
            },
            {
                "type": "json_field_contains",
                "path": "$.data.items",
                "expected": [{"tags": ["safe"]}],
            },
            {
                "type": "json_field_contains",
                "path": "$.data.items[0].name",
                "expected": "ph",
            },
            {
                "type": "header_equals",
                "path": "Content-Type",
                "expected": "application/json",
            },
            {"type": "response_time_ms_max", "expected": 50},
        ]
    )

    evidence = execute_api_cases(
        [case],
        run_id="run-assertions",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=lambda *_args, **_kwargs: FakeResponse(
            200,
            {
                "data": {
                    "optional": None,
                    "items": [
                        {
                            "name": "alpha",
                            "tags": ["safe", "sensitive-business-value"],
                        }
                    ],
                }
            },
            headers={"content-type": "application/json"},
        ),
    )

    result = evidence.cases[0]
    assert result.status == "passed"
    assert [item.passed for item in result.assertions] == [True] * 6
    value_summary = result.assertions[0].actual
    expected_digest = hashlib.sha256(
        json.dumps(
            "alpha",
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert value_summary == {
        "present": True,
        "type": "string",
        "sha256": expected_digest,
    }
    assert result.assertions[1].actual["type"] == "null"
    assert result.assertions[4].actual["type"] == "string"
    assert result.assertions[5].actual == 25
    assert result.assertions[0].expected["type"] == "string"
    assert result.assertions[4].expected["type"] == "string"
    serialized = evidence.model_dump_json()
    assert "alpha" not in serialized
    assert "application/json" not in serialized
    assert "sensitive-business-value" not in serialized
    assert "raw response value omitted" in serialized


def test_extended_assertion_failures_include_missing_and_mismatch_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = iter([0.0, 0.100, 0.101])
    monkeypatch.setattr(execution_module, "perf_counter", lambda: next(times))
    case = _case_with_assertions(
        [
            {"type": "json_field_equals", "path": "$.missing", "expected": 1},
            {
                "type": "json_field_contains",
                "path": "$.items",
                "expected": [{"state": "ready"}],
            },
            {"type": "header_equals", "path": "X-Request-Mode", "expected": "sync"},
            {"type": "response_time_ms_max", "expected": 50},
        ]
    )

    evidence = execute_api_cases(
        [case],
        run_id="run-assertions",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=lambda *_args, **_kwargs: FakeResponse(
            200,
            {"items": [{"state": "pending"}]},
        ),
    )

    result = evidence.cases[0]
    assert result.status == "failed"
    assert [item.passed for item in result.assertions] == [False] * 4
    assert result.assertions[0].actual == {"present": False}
    assert result.assertions[2].actual == {"present": False}
    assert result.assertions[3].actual == 100


@pytest.mark.parametrize(
    "assertion",
    [
        {"type": "unknown_assertion"},
        {"type": "json_field_equals", "path": "$.items[*]", "expected": 1},
        {"type": "json_field_equals", "path": "$.items"},
        {"type": "json_field_exists", "path": "$.access_token"},
        {"type": "json_field_exists", "path": "$.credential"},
        {"type": "header_equals", "path": "Set-Cookie", "expected": "value"},
        {"type": "response_time_ms_max", "expected": 0},
    ],
)
def test_invalid_assertions_are_blocked_before_authentication_or_business_request(
    assertion: dict[str, object],
) -> None:
    calls: list[tuple[str, str]] = []

    def request(method: str, url: str, **_kwargs):
        calls.append((method, url))
        return FakeResponse(200, {"access_token": "must-not-be-used"})

    evidence = execute_api_cases(
        [_case_with_assertions([assertion])],
        run_id="run-invalid-assertion",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET", "POST"],
        ),
        env={
            "TEST_BASE_URL": "https://example.test",
            "QA_API_TOKEN": "not-a-real-token",
        },
        request_func=request,
        authentication=StaticTokenApiAuthentication(
            mode="static_token",
            token_env="QA_API_TOKEN",
        ),
    )

    assert evidence.cases[0].status == "blocked"
    assert "assertion definition is invalid" in str(evidence.cases[0].error)
    assert calls == []


def test_json_assertion_on_non_json_response_records_execution_error() -> None:
    class NonJsonResponse(FakeResponse):
        def json(self):
            raise ValueError("response is not JSON")

    evidence = execute_api_cases(
        [_case_with_assertions([{"type": "json_field_equals", "path": "$.code", "expected": 0}])],
        run_id="run-non-json",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=lambda *_args, **_kwargs: NonJsonResponse(200),
    )

    assert evidence.cases[0].status == "error"
    assert evidence.cases[0].error == "json_field_equals evaluation raised ValueError"
    assert not evidence.cases[0].assertions[0].passed
    assert "response is not JSON" not in evidence.model_dump_json()


def test_response_extraction_flows_to_later_case_and_cleanup_without_evidence_leak() -> None:
    create_payload = _case("API-CREATE", "POST").model_dump(mode="python")
    create_payload["variables"] = {
        "extract": {
            "order_id": {
                "source": "response_json",
                "path": "$.data.id",
            }
        }
    }
    create_payload["cleanup"] = [
        {
            "id": "delete-order",
            "title": "delete created order",
            "request": {
                "method": "DELETE",
                "path": "/orders/${{order_id}}",
            },
            "assertions": [{"type": "status_code", "expected": 204}],
        }
    ]
    read_payload = _case("API-READ", "GET").model_dump(mode="python")
    read_payload["request"]["path"] = "/orders/${{order_id}}"
    cases = [
        ApiTestCase.model_validate(create_payload),
        ApiTestCase.model_validate(read_payload),
    ]
    calls: list[tuple[str, str]] = []

    def request(method: str, url: str, **_kwargs):
        calls.append((method, url))
        if method == "POST":
            return FakeResponse(200, {"code": 0, "data": {"id": "private-order-42"}})
        if method == "DELETE":
            return FakeResponse(204)
        return FakeResponse(200, {"code": 0})

    evidence = execute_api_cases(
        cases,
        run_id="run-variable-chain",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET", "POST", "DELETE"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=request,
    )

    assert [item[0] for item in calls] == ["POST", "GET", "DELETE"]
    assert calls[1][1].endswith("/orders/private-order-42")
    assert calls[2][1].endswith("/orders/private-order-42")
    assert evidence.summary.passed == 3
    assert evidence.cases[1].path == "/orders/${{order_id}}"
    assert evidence.cases[2].case_id == "API-CREATE::cleanup::delete-order"
    assert "private-order-42" not in evidence.model_dump_json()


def test_case_datasets_expand_requests_and_preserve_native_values() -> None:
    payload = _case("API-DATASET", "POST").model_dump(mode="python")
    payload["request"]["body"] = {
        "sku": "${{sku}}",
        "quantity": "${{quantity}}",
    }
    payload["variables"] = {
        "datasets": [
            {"id": "first", "values": {"sku": "A", "quantity": 1}},
            {"id": "second", "values": {"sku": "B", "quantity": 2}},
        ]
    }
    bodies: list[object] = []

    evidence = execute_api_cases(
        [ApiTestCase.model_validate(payload)],
        run_id="run-datasets",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["POST"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=lambda _method, _url, **kwargs: (
            bodies.append(kwargs["json"]) or FakeResponse(200, {"code": 0})
        ),
    )

    assert bodies == [{"sku": "A", "quantity": 1}, {"sku": "B", "quantity": 2}]
    assert [item.case_id for item in evidence.cases] == [
        "API-DATASET::first",
        "API-DATASET::second",
    ]
    assert evidence.summary.passed == 2


def test_invalid_runtime_variable_definition_blocks_before_authentication() -> None:
    payload = _case("API-MISSING-VAR", "GET").model_dump(mode="python")
    payload["request"]["path"] = "/orders/${{unknown_id}}"
    calls: list[bool] = []

    evidence = execute_api_cases(
        [ApiTestCase.model_validate(payload)],
        run_id="run-missing-variable",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://example.test", "QA_API_TOKEN": "runtime-token"},
        authentication=StaticTokenApiAuthentication(
            mode="static_token",
            token_env="QA_API_TOKEN",
        ),
        request_func=lambda *_args, **_kwargs: calls.append(True),
    )

    assert evidence.cases[0].status == "blocked"
    assert "not produced by an earlier case or dataset" in str(evidence.cases[0].error)
    assert calls == []


def test_missing_environment_reference_blocks_business_request() -> None:
    payload = _case("API-MISSING-ENV", "POST").model_dump(mode="python")
    payload["request"]["body"] = {"account": "${MISSING_ACCOUNT}"}
    calls: list[bool] = []

    evidence = execute_api_cases(
        [ApiTestCase.model_validate(payload)],
        run_id="run-missing-env",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["POST"],
        ),
        env={
            "TEST_BASE_URL": "https://example.test",
            "QA_API_TOKEN": "runtime-token",
        },
        authentication=StaticTokenApiAuthentication(
            mode="static_token",
            token_env="QA_API_TOKEN",
        ),
        request_func=lambda *_args, **_kwargs: calls.append(True),
    )

    assert evidence.cases[0].status == "blocked"
    assert "MISSING_ACCOUNT" in str(evidence.cases[0].error)
    assert calls == []


def test_missing_environment_reference_blocks_cleanup_request() -> None:
    payload = _case("API-CLEANUP-ENV", "POST").model_dump(mode="python")
    payload["cleanup"] = [
        {
            "id": "cleanup-env",
            "request": {
                "method": "DELETE",
                "path": "/records/cleanup",
                "headers": {"X-Fixture": "${MISSING_FIXTURE}"},
            },
            "assertions": [{"type": "status_code", "expected": 204}],
        }
    ]
    calls: list[str] = []

    evidence = execute_api_cases(
        [ApiTestCase.model_validate(payload)],
        run_id="run-cleanup-env",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["POST", "DELETE"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=lambda method, _url, **_kwargs: (
            calls.append(method) or FakeResponse(200, {"code": 0})
        ),
    )

    assert calls == []
    assert [case.status for case in evidence.cases] == ["blocked"]
    assert "MISSING_FIXTURE" in str(evidence.cases[0].error)


def test_failed_case_does_not_publish_extracted_variable_to_downstream() -> None:
    producer = _case("API-PRODUCER", "POST", expected=201).model_dump(mode="python")
    producer["variables"] = {
        "extract": {"record_id": {"source": "response_json", "path": "$.data.id"}}
    }
    consumer = _case("API-CONSUMER", "GET").model_dump(mode="python")
    consumer["request"]["path"] = "/records/${{record_id}}"
    calls: list[str] = []

    def request(method: str, url: str, **_kwargs):
        calls.append(method)
        return FakeResponse(200, {"code": 0, "data": {"id": "must-not-flow"}})

    evidence = execute_api_cases(
        [ApiTestCase.model_validate(producer), ApiTestCase.model_validate(consumer)],
        run_id="run-failed-producer",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET", "POST"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=request,
    )

    assert calls == ["POST"]
    assert [case.status for case in evidence.cases] == ["failed", "blocked"]
    assert "must-not-flow" not in evidence.model_dump_json()


def test_partial_extraction_failure_keeps_successful_values_for_cleanup() -> None:
    payload = _case("API-PARTIAL-EXTRACT", "POST").model_dump(mode="python")
    payload["variables"] = {
        "extract": {
            "record_id": {"source": "response_json", "path": "$.data.id"},
            "required_missing": {"source": "response_json", "path": "$.data.missing"},
        }
    }
    payload["cleanup"] = [
        {
            "id": "delete",
            "request": {"method": "DELETE", "path": "/records/${{record_id}}"},
            "assertions": [{"type": "status_code", "expected": 204}],
        }
    ]
    calls: list[tuple[str, str]] = []

    def request(method: str, url: str, **_kwargs):
        calls.append((method, url))
        if method == "POST":
            return FakeResponse(200, {"code": 0, "data": {"id": "cleanup-id"}})
        return FakeResponse(204)

    evidence = execute_api_cases(
        [ApiTestCase.model_validate(payload)],
        run_id="run-partial-extraction",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["POST", "DELETE"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=request,
    )

    assert [item.status for item in evidence.cases] == ["error", "passed"]
    assert calls == [
        ("POST", "https://example.test/api/api-partial-extract"),
        ("DELETE", "https://example.test/records/cleanup-id"),
    ]
    assert "cleanup-id" not in evidence.model_dump_json()


def test_assertion_exception_keeps_extracted_header_for_cleanup() -> None:
    payload = _case("API-ASSERTION-ERROR", "POST").model_dump(mode="python")
    payload["variables"] = {
        "extract": {
            "record_id": {
                "source": "response_header",
                "path": "X-Record-Id",
            }
        }
    }
    payload["cleanup"] = [
        {
            "id": "delete",
            "request": {"method": "DELETE", "path": "/records/${{record_id}}"},
            "assertions": [{"type": "status_code", "expected": 204}],
        }
    ]
    calls: list[tuple[str, str]] = []

    class InvalidJsonResponse(FakeResponse):
        def json(self):
            raise ValueError("private response content")

    def request(method: str, url: str, **_kwargs):
        calls.append((method, url))
        if method == "POST":
            return InvalidJsonResponse(200, headers={"X-Record-Id": "cleanup-id"})
        return FakeResponse(204)

    evidence = execute_api_cases(
        [ApiTestCase.model_validate(payload)],
        run_id="run-assertion-error-cleanup",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["POST", "DELETE"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=request,
    )

    assert [item.status for item in evidence.cases] == ["error", "passed"]
    assert calls == [
        ("POST", "https://example.test/api/api-assertion-error"),
        ("DELETE", "https://example.test/records/cleanup-id"),
    ]
    serialized = evidence.model_dump_json()
    assert "private response content" not in serialized
    assert "cleanup-id" not in serialized


@pytest.mark.parametrize(
    "assertion",
    [
        {"type": "json_field_equals", "path": "$.access_token", "expected": "value"},
        {
            "type": "json_field_contains",
            "path": "$.data",
            "expected": {"password": "guess-value"},
        },
        {
            "type": "json_field_equals",
            "path": "$.data.message",
            "expected": "Bearer secret-value",
        },
        {
            "type": "header_equals",
            "path": "X-Debug",
            "expected": "token=secret-value",
        },
    ],
)
def test_sensitive_assertion_expected_is_blocked_before_request(
    assertion: dict[str, object],
) -> None:
    calls: list[bool] = []
    evidence = execute_api_cases(
        [_case_with_assertions([assertion])],
        run_id="run-sensitive-expected",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=lambda *_args, **_kwargs: calls.append(True),
    )

    assert evidence.cases[0].status == "blocked"
    assert "sensitive" in str(evidence.cases[0].error).lower()
    assert calls == []


def test_dataset_and_cleanup_values_are_redacted_from_errors() -> None:
    payload = _case("API-REDACT-SCOPE", "POST").model_dump(mode="python")
    payload["request"]["body"] = {"customer": "${{customer}}"}
    payload["variables"] = {
        "datasets": [{"id": "private", "values": {"customer": "private-customer"}}],
        "extract": {"record_id": {"source": "response_json", "path": "$.data.id"}},
    }
    payload["cleanup"] = [
        {
            "id": "delete",
            "request": {"method": "DELETE", "path": "/records/${{record_id}}"},
            "assertions": [{"type": "status_code", "expected": 204}],
        }
    ]

    def request(method: str, url: str, **kwargs):
        if method == "POST":
            return FakeResponse(200, {"code": 0, "data": {"id": "private-record"}})
        raise RuntimeError(f"cleanup failed: {url} {kwargs} private-customer private-record")

    evidence = execute_api_cases(
        [ApiTestCase.model_validate(payload)],
        run_id="run-redaction-scope",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["POST", "DELETE"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=request,
    )

    serialized = evidence.model_dump_json()
    assert evidence.cases[-1].status == "error"
    assert "private-customer" not in serialized
    assert "private-record" not in serialized


@pytest.mark.parametrize(
    ("request_update", "message"),
    [
        ({"path": "//outside.test/path"}, "path"),
        ({"path": "/safe?next=/outside"}, "path"),
        ({"headers": {"Host": "outside.test"}}, "transport"),
        ({"headers": {"X-Test": "safe\r\nInjected: true"}}, "header"),
        ({"headers": {"Authorization": "Bearer inline-token"}}, "sensitive"),
        ({"body": {"password": "inline-password"}}, "sensitive"),
    ],
)
def test_ordinary_request_reuses_path_header_and_secret_safety_validation(
    request_update: dict[str, object],
    message: str,
) -> None:
    payload = _case("API-REQUEST-SAFETY", "POST").model_dump(mode="python")
    payload["request"].update(request_update)
    calls: list[bool] = []

    evidence = execute_api_cases(
        [ApiTestCase.model_validate(payload)],
        run_id="run-request-safety",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["POST"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=lambda *_args, **_kwargs: calls.append(True),
    )

    assert evidence.cases[0].status == "blocked"
    assert message in str(evidence.cases[0].error).lower()
    assert calls == []


def test_resolved_request_rejects_header_injection_before_sending() -> None:
    payload = _case("API-RESOLVED-HEADER", "GET").model_dump(mode="python")
    payload["request"]["headers"] = {"X-Fixture": "${UNSAFE_HEADER}"}
    calls: list[bool] = []

    evidence = execute_api_cases(
        [ApiTestCase.model_validate(payload)],
        run_id="run-resolved-header",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={
            "TEST_BASE_URL": "https://example.test",
            "UNSAFE_HEADER": "safe\r\nInjected: true",
        },
        request_func=lambda *_args, **_kwargs: calls.append(True),
    )

    assert evidence.cases[0].status == "blocked"
    assert "header" in str(evidence.cases[0].error).lower()
    assert calls == []


def test_json_value_comparison_distinguishes_boolean_integer_and_float_types() -> None:
    case = _case_with_assertions(
        [
            {"type": "json_field_equals", "path": "$.boolean", "expected": True},
            {"type": "json_field_equals", "path": "$.integer", "expected": 1},
            {
                "type": "json_field_contains",
                "path": "$.nested",
                "expected": {"value": True},
            },
        ]
    )

    evidence = execute_api_cases(
        [case],
        run_id="run-strict-json-types",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="qa",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=lambda *_args, **_kwargs: FakeResponse(
            200,
            {"boolean": 1, "integer": 1.0, "nested": {"value": 1}},
        ),
    )

    assert [assertion.passed for assertion in evidence.cases[0].assertions] == [
        False,
        False,
        False,
    ]


def test_runtime_definition_rejects_variable_shadowing_and_reserved_case_ids() -> None:
    producer_payload = _case("API-PRODUCER", "POST").model_dump(mode="python")
    producer_payload["variables"] = {
        "extract": {"record_id": {"source": "response_json", "path": "$.data.id"}}
    }
    duplicate_payload = _case("API-DUPLICATE", "GET").model_dump(mode="python")
    duplicate_payload["variables"] = {
        "extract": {"record_id": {"source": "response_json", "path": "$.data.id"}}
    }
    shadow_payload = _case("API-SHADOW", "GET").model_dump(mode="python")
    shadow_payload["variables"] = {
        "datasets": [{"id": "shadow", "values": {"record_id": "local-value"}}]
    }
    reserved_payload = _case("API::RESERVED", "GET").model_dump(mode="python")

    duplicate_errors = api_case_runtime_definition_errors(
        [
            ApiTestCase.model_validate(producer_payload),
            ApiTestCase.model_validate(duplicate_payload),
        ]
    )
    shadow_errors = api_case_runtime_definition_errors(
        [
            ApiTestCase.model_validate(producer_payload),
            ApiTestCase.model_validate(shadow_payload),
        ]
    )
    reserved_errors = api_case_runtime_definition_errors(
        [ApiTestCase.model_validate(reserved_payload)]
    )

    assert duplicate_errors[0] is None
    assert "already defined" in str(duplicate_errors[1])
    assert "shadow" in str(shadow_errors[1])
    assert "reserved" in str(reserved_errors[0])


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
    case.request.headers["authorization"] = "${STALE_AUTHORIZATION}"
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
            "STALE_AUTHORIZATION": "stale-value",
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


def test_phone_login_encrypts_fields_checks_business_code_and_injects_token() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []
    fixture_key = "test-key-16-byte"

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/member/app/login/phoneLogin"):
            payload = kwargs["json"]
            assert payload["telCode"] == "+86"
            assert payload["phone"] != "fixture-phone"
            assert payload["smsCode"] != "000000"
            assert _decrypt_login_fixture(payload["phone"], fixture_key) == "fixture-phone"
            assert _decrypt_login_fixture(payload["smsCode"], fixture_key) == "000000"
            return FakeResponse(
                200,
                {
                    "code": 1000,
                    "data": {"userInfo": {"accessToken": "runtime-access-token"}},
                },
            )
        return FakeResponse(200, {"code": 1000})

    authentication = LoginApiAuthentication.model_validate(
        {
            "mode": "login",
            "request": {
                "path": "/member/app/login/phoneLogin",
                "body": {
                    "telCode": "${MEMBER_API_TEL_CODE}",
                    "phone": "${MEMBER_API_PHONE}",
                    "smsCode": "${MEMBER_API_SMS_CODE}",
                },
            },
            "request_encryption": {
                "algorithm": "aes-128-cbc-pkcs7-base64-iv-prefix",
                "key_env": "MEMBER_API_LOGIN_ENCRYPTION_KEY",
                "fields": ["phone", "smsCode"],
            },
            "success_condition": {"json_path": "$.code", "expected": 1000},
            "token_json_path": "$.data.userInfo.accessToken",
            "injection": {"name": "accesstoken", "prefix": ""},
        }
    )
    evidence = execute_api_cases(
        [_case("API-MEMBER", "GET")],
        run_id="run-member-login",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="dev",
            base_url_env="MEMBER_API_BASE_URL",
            allowed_http_methods=["GET", "POST"],
        ),
        env={
            "MEMBER_API_BASE_URL": "https://member.example.test",
            "MEMBER_API_TEL_CODE": "+86",
            "MEMBER_API_PHONE": "fixture-phone",
            "MEMBER_API_SMS_CODE": "000000",
            "MEMBER_API_LOGIN_ENCRYPTION_KEY": fixture_key,
        },
        authentication=authentication,
        request_func=request,
    )

    assert evidence.summary.passed == 1
    assert len(calls) == 2
    assert calls[1][2]["headers"] == {"accesstoken": "runtime-access-token"}
    serialized = evidence.model_dump_json()
    assert "fixture-phone" not in serialized
    assert fixture_key not in serialized
    assert "runtime-access-token" not in serialized


def test_phone_login_business_failure_blocks_downstream_request() -> None:
    calls: list[str] = []
    authentication = LoginApiAuthentication.model_validate(
        {
            "mode": "login",
            "request": {
                "path": "/member/app/login/phoneLogin",
                "body": {
                    "phone": "${MEMBER_API_PHONE}",
                    "smsCode": "${MEMBER_API_SMS_CODE}",
                },
            },
            "request_encryption": {
                "algorithm": "aes-128-cbc-pkcs7-base64-iv-prefix",
                "key_env": "MEMBER_API_LOGIN_ENCRYPTION_KEY",
                "fields": ["phone", "smsCode"],
            },
            "success_condition": {"json_path": "$.code", "expected": 1000},
            "token_json_path": "$.data.userInfo.accessToken",
        }
    )

    with pytest.raises(RuntimeError, match="business success condition"):
        execute_api_cases(
            [_case("API-MEMBER", "GET")],
            run_id="run-member-login-failure",
            source_cases_path="published/api_test_draft/current.yml",
            profile=ExecutionProfile(
                environment="dev",
                base_url_env="MEMBER_API_BASE_URL",
                allowed_http_methods=["GET", "POST"],
            ),
            env={
                "MEMBER_API_BASE_URL": "https://member.example.test",
                "MEMBER_API_PHONE": "fixture-phone",
                "MEMBER_API_SMS_CODE": "000000",
                "MEMBER_API_LOGIN_ENCRYPTION_KEY": "test-key-16-byte",
            },
            authentication=authentication,
            request_func=lambda *_args, **_kwargs: (
                calls.append("login")
                or FakeResponse(200, {"code": 1001, "message": "fixture failure"})
            ),
        )

    assert calls == ["login"]


def test_phone_login_encryption_real_local_http_smoke() -> None:
    authentication = LoginApiAuthentication.model_validate(
        {
            "mode": "login",
            "request": {
                "path": "/member/app/login/phoneLogin",
                "headers": {"Accept": "application/json"},
                "body": {
                    "inviteCode": None,
                    "telCode": "${MEMBER_API_TEL_CODE}",
                    "phone": "${MEMBER_API_PHONE}",
                    "smsCode": "${MEMBER_API_SMS_CODE}",
                    "imageCode": None,
                    "registrationId": None,
                },
            },
            "request_encryption": {
                "algorithm": "aes-128-cbc-pkcs7-base64-iv-prefix",
                "key_env": "MEMBER_API_LOGIN_ENCRYPTION_KEY",
                "fields": ["phone", "smsCode"],
            },
            "success_condition": {"json_path": "$.code", "expected": 1000},
            "token_json_path": "$.data.userInfo.accessToken",
            "injection": {"name": "accesstoken", "prefix": ""},
        }
    )

    with _encrypted_member_api_server() as (base_url, requests_seen, fixture_key):
        evidence = execute_api_cases(
            [_case("API-MEMBER-LOCAL", "GET")],
            run_id="run-member-local",
            source_cases_path="published/api_test_draft/current.yml",
            profile=ExecutionProfile(
                environment="local-test",
                base_url_env="MEMBER_API_BASE_URL",
                allowed_http_methods=["GET", "POST"],
            ),
            env={
                "MEMBER_API_BASE_URL": base_url,
                "MEMBER_API_TEL_CODE": "+86",
                "MEMBER_API_PHONE": "fixture-phone",
                "MEMBER_API_SMS_CODE": "000000",
                "MEMBER_API_LOGIN_ENCRYPTION_KEY": fixture_key,
            },
            authentication=authentication,
        )

    assert evidence.summary.passed == 1
    assert requests_seen == [
        ("/member/app/login/phoneLogin", None),
        ("/api/api-member-local", "local-member-token"),
    ]


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
            "trusted_origins": ["https://example.test/"],
            "api_auth": {
                "mode": "static_token",
                "token_env": "QA_API_TOKEN",
            },
        }
    )
    login = ExecutionEnvironmentPolicy.model_validate(
        {
            "base_url_env": "TEST_BASE_URL",
            "trusted_origins": ["https://example.test"],
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
    assert static.trusted_origins == ["https://example.test"]


@pytest.mark.parametrize(
    "policy",
    [
        {"base_url_env": "TEST_BASE_URL"},
        {
            "base_url_env": "TEST_BASE_URL",
            "trusted_origins": ["http://example.test"],
        },
        {
            "base_url_env": "TEST_BASE_URL",
            "trusted_origins": ["https://example.test/api"],
        },
    ],
)
def test_workspace_execution_policy_requires_https_trusted_origins(
    policy: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        ExecutionEnvironmentPolicy.model_validate(policy)


@pytest.mark.parametrize(
    ("base_url", "message"),
    [
        ("http://example.test", "HTTPS"),
        ("https://outside.test", "not trusted"),
    ],
)
def test_execution_enforces_workspace_trusted_origins_before_request(
    base_url: str,
    message: str,
) -> None:
    calls: list[bool] = []
    with pytest.raises(ValueError, match=message):
        execute_api_cases(
            [_case("API-TRUSTED-ORIGIN", "GET")],
            run_id="run-trusted-origin",
            source_cases_path="published/api_test_draft/current.yml",
            profile=ExecutionProfile(
                environment="qa",
                base_url_env="TEST_BASE_URL",
                allowed_http_methods=["GET"],
            ),
            env={"TEST_BASE_URL": base_url},
            request_func=lambda *_args, **_kwargs: calls.append(True),
            trusted_origins=["https://example.test"],
        )
    assert calls == []
