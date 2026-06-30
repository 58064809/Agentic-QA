from __future__ import annotations

import json

from runtime.tools.api_discovery_normalizer import load_network_capture


def test_network_capture_filters_static_and_merges_api_calls(tmp_path):
    capture = {
        "calls": [
            {
                "method": "GET",
                "url": "https://example.test/static/app.js",
                "resource_type": "script",
                "status": 200,
            },
            {
                "method": "POST",
                "url": "https://example.test/api/activity/join",
                "status": 200,
                "request_body": {"activityId": "A1", "phone": "13800138000"},
                "response_body": {"code": 0, "data": {"status": "joined"}},
                "duration_ms": 30,
            },
            {
                "method": "POST",
                "url": "https://example.test/api/activity/join",
                "status": 200,
                "request_body": {"activityId": "A1"},
                "response_body": {"code": 0, "data": {"status": "joined"}},
                "duration_ms": 50,
            },
        ]
    }
    path = tmp_path / "network-capture.json"
    path.write_text(json.dumps(capture), encoding="utf-8")

    result = load_network_capture(path)

    assert len(result.calls) == 3
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.path == "/api/activity/join"
    assert candidate.call_count == 2
    assert candidate.avg_duration_ms == 40
    assert candidate.request_schema["phone"] == "string"


def test_har_entries_are_parsed_and_sanitized(tmp_path):
    har = {
        "log": {
            "entries": [
                {
                    "request": {
                        "method": "GET",
                        "url": "https://example.test/api/profile",
                        "headers": [{"name": "Authorization", "value": "Bearer abcdefghijklmnop"}],
                    },
                    "response": {
                        "status": 200,
                        "headers": [{"name": "Set-Cookie", "value": "sid=secret"}],
                        "content": {"text": '{"phone":"13800138000"}'},
                    },
                    "time": 12,
                }
            ]
        }
    }
    path = tmp_path / "network-capture.har"
    path.write_text(json.dumps(har), encoding="utf-8")

    result = load_network_capture(path)

    assert result.calls[0].request_headers["Authorization"] == "<REDACTED>"
    assert result.calls[0].response_headers["Set-Cookie"] == "<REDACTED>"
    assert result.calls[0].response_body_schema["phone"] == "string"
