from __future__ import annotations

import pytest

from harness.application.source import (
    SourceBundle,
    SourceCompleteness,
    SourceDocument,
    SourceIngestionLimits,
)
from harness.domain.schemas.api_test_cases import ApiAssertion, ApiTestCasesDraft
from harness.infrastructure.tools.openapi import inspect_openapi
from harness.infrastructure.workflow.engine import _validate_api_test_cases


def test_openapi_3_normalizes_parameters_body_responses_security_and_refs() -> None:
    inspection = inspect_openapi(
        {
            "openapi": "3.1.0",
            "info": {"title": "Benefits", "version": "1"},
            "servers": [{"url": "https://api.example.test"}],
            "components": {
                "schemas": {
                    "AssistRequest": {
                        "type": "object",
                        "required": ["user_id"],
                        "properties": {"user_id": {"type": "string"}},
                    }
                },
                "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
            },
            "security": [{"bearerAuth": []}],
            "paths": {
                "/activities/{activity_id}/assist": {
                    "parameters": [
                        {
                            "name": "activity_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "post": {
                        "operationId": "assist",
                        "tags": ["benefits"],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AssistRequest"}
                                }
                            },
                        },
                        "responses": {
                            "200": {
                                "description": "accepted",
                                "headers": {"X-Result": {"schema": {"type": "string"}}},
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {"accepted": {"type": "boolean"}},
                                        }
                                    }
                                },
                            }
                        },
                    },
                }
            },
        },
        source="sources/openapi.yml",
    ).model_dump(mode="json", by_alias=True)

    assert inspection["server_urls"] == ["https://api.example.test"]
    assert inspection["security_schemes"]["bearerAuth"]["scheme"] == "bearer"
    endpoint = inspection["endpoints"][0]
    assert endpoint["parameters"][0] == {
        "name": "activity_id",
        "location": "path",
        "required": True,
        "description": "",
        "schema": {"type": "string"},
    }
    assert endpoint["request_body"]["content"]["application/json"]["required"] == ["user_id"]
    assert endpoint["responses"][0]["status"] == "200"
    assert endpoint["responses"][0]["headers"] == {"X-Result": {"type": "string"}}
    assert endpoint["security"] == [{"bearerAuth": []}]


def test_swagger_2_normalizes_body_response_and_server() -> None:
    inspection = inspect_openapi(
        {
            "swagger": "2.0",
            "info": {"title": "Legacy", "version": "1"},
            "host": "legacy.example.test",
            "basePath": "/v1",
            "schemes": ["https"],
            "consumes": ["application/json"],
            "produces": ["application/json"],
            "definitions": {
                "Request": {
                    "type": "object",
                    "properties": {"code": {"type": "string"}},
                }
            },
            "paths": {
                "/draw": {
                    "post": {
                        "parameters": [
                            {
                                "name": "body",
                                "in": "body",
                                "required": True,
                                "schema": {"$ref": "#/definitions/Request"},
                            }
                        ],
                        "responses": {
                            "201": {
                                "description": "created",
                                "schema": {"type": "object"},
                            }
                        },
                    }
                }
            },
        },
        source="sources/swagger.json",
    ).model_dump(mode="json", by_alias=True)

    endpoint = inspection["endpoints"][0]
    assert inspection["specification"] == "swagger"
    assert inspection["server_urls"] == ["https://legacy.example.test/v1"]
    assert endpoint["parameters"] == []
    assert endpoint["request_body"] == {
        "required": True,
        "description": "",
        "content": {
            "application/json": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
            }
        },
    }
    assert endpoint["responses"][0]["content"] == {"application/json": {"type": "object"}}


def test_openapi_inspection_decodes_percent_encoded_local_reference_parts() -> None:
    inspection = inspect_openapi(
        {
            "openapi": "3.1.0",
            "info": {"title": "Encoded ref", "version": "1"},
            "paths": {
                "/status": {
                    "get": {
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {"$ref": "#/components/schemas/Wrapper%3F"}
                                    }
                                },
                            }
                        }
                    }
                }
            },
            "components": {
                "schemas": {
                    "Wrapper?": {
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                    }
                }
            },
        },
        source="sources/openapi.json",
    )

    assert inspection.endpoints[0].responses[0].content["application/json"]["type"] == "object"


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"openapi": "2.0", "paths": {"/x": {"get": {}}}}, "supported"),
        ({"openapi": "3.1.0", "paths": {}}, "no paths"),
        (
            {
                "openapi": "3.1.0",
                "paths": {
                    "/x": {
                        "get": {
                            "parameters": [
                                {
                                    "$ref": "https://example.test/parameters.yml#/Trace",
                                }
                            ]
                        }
                    }
                },
            },
            "external",
        ),
    ],
)
def test_openapi_inspection_rejects_incomplete_or_external_contracts(
    payload: dict, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        inspect_openapi(payload, source="sources/openapi.yml")


def test_confirmed_api_case_requires_endpoint_from_inspected_frozen_contract() -> None:
    draft = ApiTestCasesDraft.model_validate(
        {
            "schema_version": "agentic-qa.api-cases.v1.1",
            "artifact_type": "api_automation_cases",
            "status": "needs_human_review",
            "human_review_required": True,
            "base_url_env": "AGENTIC_QA_BASE_URL",
            "business_rules": ["RULE-001"],
            "source_refs": [
                {
                    "source_type": "openapi",
                    "source_path": "sources/openapi.yml",
                    "chunk_id": "post-assist",
                    "locator": "POST /assist",
                    "summary": "助力接口",
                    "confidence": "high",
                }
            ],
            "cases": [
                {
                    "id": "API-001",
                    "title": "提交助力",
                    "priority": "P0",
                    "contract_status": "confirmed",
                    "business_rule_refs": ["RULE-001"],
                    "review_status": "needs_human_review",
                    "review_questions": ["测试数据由人工选择"],
                    "source_refs": [
                        {
                            "source_type": "openapi",
                            "source_path": "sources/openapi.yml",
                            "chunk_id": "post-assist",
                            "locator": "POST /assist",
                            "summary": "助力接口",
                            "confidence": "high",
                        }
                    ],
                    "pending": [],
                    "request": {"method": "POST", "path": "/assist"},
                    "assertions": [{"type": "status_code", "expected": [200]}],
                    "variables": {},
                    "cleanup": [],
                }
            ],
            "review_questions": ["测试环境由人工确认"],
        }
    )
    frozen = SourceBundle(
        parser_version="test",
        limits=SourceIngestionLimits(),
        documents=(
            SourceDocument(
                path="sources/openapi.yml",
                raw_sha256="sha256:" + "0" * 64,
                parsed_sha256="sha256:" + "1" * 64,
                byte_size=1,
                text="openapi: 3.1.0",
                completeness=SourceCompleteness.COMPLETE,
            ),
        ),
        completeness=SourceCompleteness.COMPLETE,
        bundle_hash="sha256:" + "2" * 64,
    )
    inspection = {
        "tool": "openapi.inspect",
        "result": inspect_openapi(
            {
                "openapi": "3.1.0",
                "info": {"title": "Assist", "version": "1"},
                "paths": {"/assist": {"post": {"responses": {"200": {"description": "accepted"}}}}},
            },
            source="sources/openapi.yml",
        ).model_dump(mode="json", by_alias=True),
    }

    _validate_api_test_cases(
        draft,
        tool_results=[inspection],
        requirement_catalog=None,
        source_bundle=frozen,
    )
    invalid_case = draft.cases[0].model_copy(
        update={"assertions": [ApiAssertion(type="unknown_assertion")]}
    )
    invalid_draft = draft.model_copy(update={"cases": [invalid_case]})
    with pytest.raises(ValueError, match="invalid API assertions"):
        _validate_api_test_cases(
            invalid_draft,
            tool_results=[inspection],
            requirement_catalog=None,
            source_bundle=frozen,
        )
    invalid_runtime_case = draft.cases[0].model_copy(
        update={
            "request": draft.cases[0].request.model_copy(update={"path": "/assist/${{missing_id}}"})
        }
    )
    with pytest.raises(ValueError, match="invalid API runtime definitions"):
        _validate_api_test_cases(
            draft.model_copy(update={"cases": [invalid_runtime_case]}),
            tool_results=[inspection],
            requirement_catalog=None,
            source_bundle=frozen,
        )
    with pytest.raises(ValueError, match="unverified endpoint"):
        _validate_api_test_cases(
            draft,
            tool_results=[],
            requirement_catalog=None,
            source_bundle=frozen,
        )

    parameter_inspection = {
        "tool": "openapi.inspect",
        "result": inspect_openapi(
            {
                "openapi": "3.1.0",
                "info": {"title": "Assist", "version": "1"},
                "paths": {
                    "/assist/{assist_id}": {
                        "parameters": [
                            {
                                "name": "assist_id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "integer", "minimum": 1, "maximum": 2},
                            }
                        ],
                        "post": {"responses": {"200": {"description": "accepted"}}},
                    }
                },
            },
            source="sources/openapi.yml",
        ).model_dump(mode="json", by_alias=True),
    }
    path_case = draft.cases[0].model_copy(
        update={
            "request": draft.cases[0].request.model_copy(update={"path": "/assist/${{assist_id}}"}),
            "variables": {"datasets": [{"id": "valid", "values": {"assist_id": 1}}]},
            "source_refs": [
                reference.model_copy(update={"locator": "POST /assist/{assist_id}"})
                for reference in draft.cases[0].source_refs
            ],
        }
    )
    _validate_api_test_cases(
        draft.model_copy(update={"cases": [path_case]}),
        tool_results=[parameter_inspection],
        requirement_catalog=None,
        source_bundle=frozen,
    )
    invalid_path_case = path_case.model_copy(
        update={"variables": {"datasets": [{"id": "invalid", "values": {"assist_id": 3}}]}}
    )
    with pytest.raises(ValueError, match="invalid API contract semantics"):
        _validate_api_test_cases(
            draft.model_copy(update={"cases": [invalid_path_case]}),
            tool_results=[parameter_inspection],
            requirement_catalog=None,
            source_bundle=frozen,
        )
