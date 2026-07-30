from __future__ import annotations

from typing import Any

import pytest

from harness.infrastructure.tools.playwright_network import inspect_playwright_network


def _result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def test_live_capture_normalizes_and_redacts_mcp_network_details() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_mcp(payload: dict[str, Any]) -> dict[str, Any]:
        tool = payload["tool"]
        arguments = payload["arguments"]
        calls.append((tool, arguments))
        if tool == "browser_network_requests":
            return _result(
                "### Result\n"
                "1. [GET] https://qa.example.test/ => [200]\n"
                "2. [POST] https://api.example.test/api/activities/123/assist"
                "?token=query-secret&q=campaign => [409] Conflict"
            )
        index = arguments["index"]
        part = arguments.get("part")
        if index == 1:
            return _result(
                "### Result\n"
                "#1 [GET] https://qa.example.test/\n\n"
                "  General\n"
                "    status: [200]\n"
                "    duration: 15ms\n"
                "    type: document\n"
                "    mimeType: text/html\n"
            )
        if part == "request-body":
            return _result(
                '### Result\n{"activity_id":123,"phone":"13800138000","token":"request-secret"}'
            )
        if part == "response-body":
            return _result('### Result\n{"accepted":false,"access_token":"response-secret"}')
        return _result(
            "### Result\n"
            "#2 [POST] https://api.example.test/api/activities/123/assist"
            "?token=query-secret&q=campaign\n\n"
            "  General\n"
            "    status: [409]\n"
            "    duration: 45ms\n"
            "    type: xhr\n"
            "    mimeType: application/json\n\n"
            "  Request headers\n"
            "    authorization: Bearer raw-secret\n"
            "    content-type: application/json\n"
            "    cookie: sid=raw-secret\n\n"
            "  Response headers\n"
            "    content-type: application/json\n"
            "    set-cookie: sid=response-secret\n"
        )

    catalog = inspect_playwright_network(
        call_mcp,
        max_requests=25,
        source="runtime/playwright-network-capture/run-test",
    )

    assert catalog.schema_version == "agentic-qa.api-discovery.v1.1"
    assert catalog.capture_format == "playwright_mcp"
    assert catalog.observed_call_count == 2
    assert catalog.business_candidate_count == 1
    candidate = catalog.candidates[0]
    assert candidate.origin == "https://api.example.test"
    assert candidate.path == "/api/activities/{id}/assist"
    assert candidate.status_codes == [409]
    assert candidate.query_parameters == ["q", "token"]
    assert candidate.request_schema["properties"]["phone"]["redacted"] is True
    assert candidate.response_schema["properties"]["access_token"]["redacted"] is True
    assert "request_header:authorization" in catalog.redactions
    assert "response_header:set-cookie" in catalog.redactions
    rendered = catalog.model_dump_json()
    for secret in (
        "query-secret",
        "raw-secret",
        "request-secret",
        "response-secret",
        "13800138000",
    ):
        assert secret not in rendered
    assert (
        "browser_network_request",
        {"index": 1, "part": "response-body"},
    ) not in calls


def test_live_capture_bounds_requests_and_records_detail_failures() -> None:
    def call_mcp(payload: dict[str, Any]) -> dict[str, Any]:
        if payload["tool"] == "browser_network_requests":
            return _result(
                "### Result\n"
                + "\n".join(
                    f"{index}. [GET] https://qa.example.test/api/items/{index} => [200]"
                    for index in range(1, 4)
                )
            )
        return _result("### Error\nrequest unavailable", is_error=True)

    catalog = inspect_playwright_network(
        call_mcp,
        max_requests=2,
        source="runtime/playwright-network-capture/run-test",
    )

    assert catalog.observed_call_count == 2
    assert catalog.business_candidate_count == 1
    assert catalog.candidates[0].call_count == 2
    assert any("前 2 条" in item for item in catalog.limitations)
    assert any("2 条请求详情不可用" in item for item in catalog.limitations)


def test_live_capture_rejects_an_mcp_list_error() -> None:
    with pytest.raises(RuntimeError, match="returned an error"):
        inspect_playwright_network(
            lambda _payload: _result("### Error\nbrowser closed", is_error=True),
            max_requests=25,
            source="runtime/playwright-network-capture/run-test",
        )
