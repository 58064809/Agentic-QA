from __future__ import annotations

import json
from pathlib import Path

from runtime.tools.network_capture import NetworkCapture


class FakeRequest:
    method = "POST"
    headers = {
        "Authorization": "Bearer should-not-leak",
        "Cookie": "sid=should-not-leak",
        "X-Api-Key": "should-not-leak",
    }
    post_data = json.dumps(
        {
            "token": "request-token-should-not-leak",
            "phone": "13812345678",
            "activityId": "A1",
        },
        ensure_ascii=False,
    )


class FakeResponse:
    url = "https://example.test/api/activity/join"
    status = 200
    request = FakeRequest()
    headers = {
        "content-type": "application/json",
        "set-cookie": "sid=response-cookie-should-not-leak",
    }

    def text(self) -> str:
        return json.dumps(
            {
                "access_token": "response-token-should-not-leak",
                "phone": "13812345678",
                "idCard": "11010519491231002X",
                "bankCard": "6222020202020202020",
                "data": {"status": "joined"},
            },
            ensure_ascii=False,
        )


def _serialized(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_network_capture_default_saves_schema_without_full_body(tmp_path):
    capture = NetworkCapture()
    capture.on_response(FakeResponse())
    output = capture.save(tmp_path / "network-capture.json")

    payload = json.loads(output.read_text(encoding="utf-8"))
    entry = payload["log"]["entries"][0]

    assert "response_body" not in entry
    assert "request_body" not in entry
    assert entry["request_headers"]["Authorization"] == "<REDACTED>"
    assert entry["request_headers"]["Cookie"] == "<REDACTED>"
    assert entry["request_headers"]["X-Api-Key"] == "<REDACTED>"
    assert entry["response_headers"]["set-cookie"] == "<REDACTED>"
    assert entry["request_body_schema"] == {
        "token": "string",
        "phone": "string",
        "activityId": "string",
    }
    assert entry["response_body_schema"]["data"] == {"status": "string"}
    serialized = _serialized(output)
    assert "should-not-leak" not in serialized
    assert "13812345678" not in serialized
    assert "11010519491231002X" not in serialized
    assert "6222020202020202020" not in serialized


def test_network_capture_save_body_redacts_sensitive_values(tmp_path):
    capture = NetworkCapture(save_body=True)
    capture.on_response(FakeResponse())
    output = capture.save(tmp_path / "network-capture.json")

    serialized = _serialized(output)
    payload = json.loads(serialized)
    entry = payload["log"]["entries"][0]

    assert "response_body" in entry
    assert "<REDACTED>" in serialized
    assert "should-not-leak" not in serialized
    assert "13812345678" not in serialized
    assert "11010519491231002X" not in serialized
    assert "6222020202020202020" not in serialized
