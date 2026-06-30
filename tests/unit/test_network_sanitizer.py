from __future__ import annotations

from runtime.tools.network_sanitizer import sanitize_headers, sanitize_json, schema_summary


def test_headers_and_token_fields_are_redacted():
    headers = sanitize_headers(
        {"Authorization": "Bearer real-token", "Cookie": "sid=abc", "X": "ok"}
    )
    body = sanitize_json({"access_token": "secret-token", "phone": "13800138000"})

    assert headers["Authorization"] == "<REDACTED>"
    assert headers["Cookie"] == "<REDACTED>"
    assert body["access_token"] == "<REDACTED>"
    assert body["phone"] == "138****8000"


def test_response_body_schema_summary_does_not_keep_values():
    schema = schema_summary({"code": 0, "message": "ok", "data": {"id": "abc"}})

    assert schema == {"code": "number", "message": "string", "data": {"id": "string"}}
