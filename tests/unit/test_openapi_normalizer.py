from __future__ import annotations

import pytest

from runtime.tools.openapi_normalizer import normalize_openapi_document, render_openapi_markdown


def openapi3_payload() -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Activity API", "version": "1.0"},
        "components": {"securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}}},
        "security": [{"BearerAuth": []}],
        "paths": {
            "/api/activity/join": {
                "post": {
                    "operationId": "joinActivity",
                    "summary": "参加活动",
                    "tags": ["activity"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["activityId"],
                                    "properties": {
                                        "activityId": {"type": "string"},
                                        "inviteCode": {"type": "string"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"code": {"type": "integer"}},
                                    }
                                }
                            },
                        },
                        "401": {"description": "unauthorized"},
                    },
                }
            }
        },
    }


def test_openapi3_json_normalizes_required_fields_and_security():
    document = normalize_openapi_document(openapi3_payload(), source_path="api.json")

    assert document.spec_type == "openapi-3.0.3"
    assert len(document.endpoints) == 1
    endpoint = document.endpoints[0]
    assert endpoint.method == "POST"
    assert endpoint.path == "/api/activity/join"
    assert endpoint.request_body_schema["required"] == ["activityId"]
    assert endpoint.auth_requirements == ["BearerAuth"]
    assert endpoint.success_codes == ["200"]
    assert endpoint.error_codes == ["401"]


def test_swagger2_json_normalizes_body_schema():
    payload = {
        "swagger": "2.0",
        "info": {"title": "Swagger API", "version": "1.0"},
        "securityDefinitions": {"ApiKeyAuth": {"type": "apiKey", "in": "header"}},
        "security": [{"ApiKeyAuth": []}],
        "paths": {
            "/api/order": {
                "post": {
                    "parameters": [
                        {
                            "name": "body",
                            "in": "body",
                            "required": True,
                            "schema": {
                                "type": "object",
                                "required": ["orderId"],
                                "properties": {"orderId": {"type": "string"}},
                            },
                        }
                    ],
                    "responses": {"200": {"description": "ok"}, "400": {"description": "bad"}},
                }
            }
        },
    }

    document = normalize_openapi_document(payload)

    endpoint = document.endpoints[0]
    assert document.spec_type == "swagger-2.0"
    assert endpoint.request_body_schema["required"] == ["orderId"]
    assert endpoint.auth_requirements == ["ApiKeyAuth"]


def test_apifox_openapi_extensions_do_not_block_normalization():
    payload = openapi3_payload()
    payload["paths"]["/api/activity/join"]["post"]["x-apifox-folder"] = "活动"

    document = normalize_openapi_document(payload)

    assert document.endpoints[0].apifox_metadata["x-apifox-folder"] == "活动"


def test_empty_paths_raise_clear_error():
    with pytest.raises(ValueError, match="paths"):
        normalize_openapi_document({"openapi": "3.0.0", "paths": {}})


def test_render_openapi_markdown_contains_method_path_and_schema():
    markdown = render_openapi_markdown(normalize_openapi_document(openapi3_payload()))

    assert "## POST /api/activity/join" in markdown
    assert "| activityId | True | string |" in markdown
    assert "BearerAuth" in markdown
