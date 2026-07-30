from __future__ import annotations

import json

import pytest

from harness.application.source import (
    SourceBundle,
    SourceCompleteness,
    SourceDocument,
    SourceIngestionLimits,
)
from harness.domain.schemas.api_test_cases import ApiTestCasesDraft
from harness.infrastructure.tools.network_capture import inspect_network_capture
from harness.infrastructure.workflow.engine import (
    _render_api_discovery_report,
    _validate_api_test_cases,
)


def _har() -> dict:
    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "Playwright", "version": "1"},
            "pages": [{"id": "page-1", "_url": "https://example.test/benefits"}],
            "entries": [
                {
                    "pageref": "page-1",
                    "_resourceType": "image",
                    "request": {
                        "method": "GET",
                        "url": "https://example.test/assets/banner.png",
                    },
                    "response": {"status": 200, "content": {"mimeType": "image/png"}},
                    "time": 2,
                },
                {
                    "pageref": "page-1",
                    "_resourceType": "xhr",
                    "request": {
                        "method": "POST",
                        "url": "https://example.test/api/activities/123/assist?token=secret&q=ok",
                        "headers": [
                            {"name": "Authorization", "value": "Bearer top-secret"},
                            {"name": "Cookie", "value": "session=top-secret"},
                        ],
                        "postData": {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {
                                    "user_id": "user-1",
                                    "phone": "13800138000",
                                    "token": "top-secret",
                                }
                            ),
                        },
                    },
                    "response": {
                        "status": 200,
                        "headers": [
                            {"name": "content-type", "value": "application/json"},
                            {"name": "set-cookie", "value": "sid=top-secret"},
                        ],
                        "content": {
                            "mimeType": "application/json",
                            "text": json.dumps(
                                {
                                    "accepted": True,
                                    "access_token": "response-secret",
                                }
                            ),
                        },
                    },
                    "time": 20,
                },
                {
                    "pageref": "page-1",
                    "_resourceType": "fetch",
                    "request": {
                        "method": "POST",
                        "url": "https://example.test/api/activities/456/assist?q=again",
                        "postData": {
                            "mimeType": "application/json",
                            "text": json.dumps({"user_id": "user-2"}),
                        },
                    },
                    "response": {
                        "status": 409,
                        "headers": [{"name": "content-type", "value": "application/json"}],
                        "content": {
                            "mimeType": "application/json",
                            "text": json.dumps({"code": "DUPLICATE"}),
                        },
                    },
                    "time": 40,
                },
            ],
        }
    }


def test_har_is_filtered_merged_sanitized_and_schema_only() -> None:
    catalog = inspect_network_capture(
        _har(),
        source="sources/network-capture.har",
    )

    assert catalog.capture_format == "har"
    assert catalog.observed_call_count == 2
    assert catalog.business_candidate_count == 1
    candidate = catalog.candidates[0]
    assert (candidate.method, candidate.path, candidate.call_count) == (
        "POST",
        "/api/activities/{id}/assist",
        2,
    )
    assert candidate.status_codes == [200, 409]
    assert candidate.average_duration_ms == 30
    assert candidate.query_parameters == ["q", "token"]
    assert candidate.locators == ["entry:2", "entry:3"]
    assert candidate.request_schema["oneOf"][0]["type"] == "object"
    rendered = catalog.model_dump_json()
    assert "top-secret" not in rendered
    assert "response-secret" not in rendered
    assert "13800138000" not in rendered
    assert "request_header:authorization" in catalog.redactions
    assert "request.phone" in catalog.redactions
    assert "response.access_token" in catalog.redactions


def test_simplified_capture_can_report_no_business_candidates() -> None:
    catalog = inspect_network_capture(
        {
            "entries": [
                {
                    "method": "GET",
                    "url": "https://example.test/help",
                    "status": 200,
                    "resource_type": "document",
                    "response_body": "<html></html>",
                },
                {
                    "method": "GET",
                    "url": "https://example.test/app.js",
                    "status": 200,
                    "resource_type": "script",
                },
            ]
        },
        source="sources/network-capture.json",
    )

    assert catalog.capture_format == "simplified_json"
    assert catalog.observed_call_count == 1
    assert catalog.business_candidate_count == 0
    assert catalog.candidates == []
    report = _render_api_discovery_report([catalog], run_id="run-test")
    assert "未发现业务接口候选" in report
    assert "不代表完整 API 契约" in report


def test_observed_network_candidate_only_supports_an_unconfirmed_api_case() -> None:
    source_path = "sources/network-capture.json"
    catalog = inspect_network_capture(
        {
            "entries": [
                {
                    "method": "POST",
                    "url": "https://example.test/api/activities/123/assist",
                    "status": 200,
                    "resource_type": "xhr",
                }
            ]
        },
        source=source_path,
    )
    source_ref = {
        "source_type": "playwright-network-capture",
        "source_path": source_path,
        "chunk_id": "entry:1",
        "locator": "entry:1",
        "summary": "页面操作期间观测到助力请求，接口契约仍待确认。",
        "confidence": "medium",
    }
    draft = ApiTestCasesDraft.model_validate(
        {
            "schema_version": "agentic-qa.api-cases.v1.1",
            "artifact_type": "api_automation_cases",
            "status": "needs_human_review",
            "human_review_required": True,
            "base_url_env": "AGENTIC_QA_BASE_URL",
            "business_rules": [{"id": "BR-001", "summary": "用户可发起助力"}],
            "source_refs": [source_ref],
            "cases": [
                {
                    "id": "API-PENDING-001",
                    "title": "待确认的助力接口候选",
                    "priority": "P1",
                    "contract_status": "pending_confirmation",
                    "business_rule_refs": ["BR-001"],
                    "review_status": "needs_human_review",
                    "review_questions": ["接口方法和路径以哪份完整 OpenAPI 为准？"],
                    "source_refs": [source_ref],
                    "pending": ["补充完整 OpenAPI 后确认方法、路径和断言。"],
                    "request": {"method": None, "path": None},
                    "assertions": [],
                    "variables": {},
                    "cleanup": [],
                }
            ],
            "review_questions": ["请补充完整 OpenAPI 契约。"],
        }
    )
    frozen = SourceBundle(
        parser_version="test",
        limits=SourceIngestionLimits(),
        documents=(
            SourceDocument(
                path=source_path,
                raw_sha256="sha256:" + "0" * 64,
                parsed_sha256="sha256:" + "1" * 64,
                byte_size=1,
                text='{"entries":[]}',
                completeness=SourceCompleteness.COMPLETE,
            ),
        ),
        completeness=SourceCompleteness.COMPLETE,
        bundle_hash="sha256:" + "2" * 64,
    )
    tool_result = {
        "tool": "network.capture.inspect",
        "result": catalog.model_dump(mode="json"),
    }

    _validate_api_test_cases(
        draft,
        tool_results=[tool_result],
        requirement_catalog=None,
        source_bundle=frozen,
    )
    with pytest.raises(ValueError, match="uninspected network captures"):
        _validate_api_test_cases(
            draft,
            tool_results=[],
            requirement_catalog=None,
            source_bundle=frozen,
        )


def test_report_escapes_untrusted_markdown_and_html() -> None:
    catalog = inspect_network_capture(
        {
            "entries": [
                {
                    "method": "POST",
                    "url": "https://example.test/api/<script>",
                    "status": 200,
                    "resource_type": "xhr",
                    "request_body": {"```break": "<img src=x>"},
                    "response_body": {"ok": True},
                }
            ]
        },
        source="sources/network`capture.json",
    )

    report = _render_api_discovery_report([catalog], run_id="run-<script>")
    assert "<script>" not in report
    assert "&lt;script&gt;" in report
    assert "```json" not in report
    assert '    "```break"' in report


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"log": {"entries": "not-an-array"}},
        {"entries": "not-an-array"},
    ],
)
def test_invalid_capture_shape_is_rejected(payload: dict) -> None:
    with pytest.raises(ValueError, match="HAR|simplified JSON"):
        inspect_network_capture(payload, source="sources/network-capture.json")
