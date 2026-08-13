from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

from harness.domain.schemas.local_config import LocalTracesConfig
from harness.domain.schemas.trace_evidence import TraceQueryRequest
from harness.infrastructure.failure_traces import TempoTraceProvider

TRACE_BYTES = bytes.fromhex("4bf92f3577b34da6a3ce929d0e0e4736")
SPAN_BYTES = bytes.fromhex("00f067aa0ba902b7")
TRACE_ID = TRACE_BYTES.hex()


def _config(max_bytes=2_097_152):
    return LocalTracesConfig.model_validate(
        {
            "provider": "tempo",
            "allowed_environments": ["qa"],
            "query": {"max_response_bytes": max_bytes},
            "tempo": {
                "base_url": "https://tempo.qa.example.com",
                "trusted_origins": ["https://tempo.qa.example.com"],
                "token": "provider-resolved-token",
                "timeout_seconds": 15,
            },
        }
    )


def _query(trace_id=TRACE_ID):
    now = datetime.now(tz=UTC).replace(microsecond=0)
    return TraceQueryRequest(
        workspace_id="workspace-1",
        execution_id="execution-1",
        case_id="CASE-1",
        environment="qa",
        trace_id=trace_id,
        started_at=now,
        completed_at=now + timedelta(seconds=1),
    )


class _Response:
    def __init__(self, payload, status=200, url=None):
        self.status_code = status
        self.url = url or f"https://tempo.qa.example.com/api/v2/traces/{TRACE_ID}"
        self.headers = {}
        self.body = json.dumps(payload).encode()

    def iter_content(self, chunk_size):
        del chunk_size
        yield self.body


def _payload():
    now_ns = int(datetime.now(tz=UTC).timestamp() * 1_000_000_000)
    return {
        "trace": {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "inventory"}}
                        ]
                    },
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": base64.b64encode(TRACE_BYTES).decode(),
                                    "spanId": base64.b64encode(SPAN_BYTES).decode(),
                                    "name": "mysql query",
                                    "kind": "SPAN_KIND_CLIENT",
                                    "startTimeUnixNano": str(now_ns),
                                    "endTimeUnixNano": str(now_ns + 50_000_000),
                                    "status": {"code": "STATUS_CODE_ERROR"},
                                    "attributes": [
                                        {"key": "db.system", "value": {"stringValue": "mysql"}},
                                        {
                                            "key": "db.statement",
                                            "value": {"stringValue": "SELECT secret FROM users"},
                                        },
                                        {
                                            "key": "exception.message",
                                            "value": {"stringValue": "password=secret-value"},
                                        },
                                    ],
                                }
                            ]
                        }
                    ],
                }
            ]
        }
    }


def test_tempo_exact_query_is_bounded_and_normalizes_allowlist() -> None:
    captured = {}

    def request(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _Response(_payload())

    result = TempoTraceProvider(_config(), request_func=request).get_trace(_query())
    assert result.status == "success"
    assert captured["url"].endswith(f"/api/v2/traces/{TRACE_ID}")
    assert captured["allow_redirects"] is False
    assert captured["headers"]["Authorization"] == "Bearer provider-resolved-token"
    span = result.spans[0]
    assert span.service == "inventory"
    assert span.db_system == "mysql"
    assert span.error_message_digest is not None
    assert "secret-value" not in span.model_dump_json()
    assert "SELECT" not in span.model_dump_json()


def test_tempo_rejects_non_hex_before_network() -> None:
    calls = []
    result = TempoTraceProvider(
        _config(), request_func=lambda *_args, **_kwargs: calls.append(True)
    ).get_trace(_query("not-hex"))
    assert result.status == "failed"
    assert not calls


def test_tempo_not_found_redirect_and_oversize_are_projection_failures() -> None:
    assert (
        TempoTraceProvider(_config(), request_func=lambda *_args, **_kwargs: _Response({}, 404))
        .get_trace(_query())
        .status
        == "not_found"
    )
    redirect = _Response({}, 302)
    assert (
        TempoTraceProvider(_config(), request_func=lambda *_args, **_kwargs: redirect)
        .get_trace(_query())
        .diagnostics[0]
        .code
        == "TEMPO_REDIRECT_REJECTED"
    )
    assert (
        TempoTraceProvider(
            _config(1024),
            request_func=lambda *_args, **_kwargs: _Response("x" * 2000),
        )
        .get_trace(_query())
        .status
        == "failed"
    )
