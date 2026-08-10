from __future__ import annotations

from typing import Any

from harness.application.api_contract_validation import validate_api_contracts
from harness.domain.schemas.api_test_cases import ApiTestCasesDraft
from harness.infrastructure.tools.openapi import inspect_openapi

SOURCE = "sources/orders.openapi.yml"


def _reference(source: str = SOURCE, locator: str = "GET /orders/{order_id}") -> dict[str, Any]:
    return {
        "source_type": "openapi",
        "source_path": source,
        "chunk_id": "orders",
        "locator": locator,
        "summary": "orders contract",
        "confidence": "high",
    }


def _case(
    *,
    case_id: str = "API-001",
    method: str = "GET",
    path: str = "/orders/${{order_id}}",
    variables: dict[str, Any] | None = None,
    body: Any = None,
    assertions: list[dict[str, Any]] | None = None,
    cleanup: list[dict[str, Any]] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    canonical_path = path.replace("${{order_id}}", "{order_id}")
    references = list(source_refs or [_reference(locator=f"{method} {canonical_path}")])
    for cleanup_step in cleanup or []:
        cleanup_request = cleanup_step.get("request") or {}
        cleanup_method = str(cleanup_request.get("method") or "").upper()
        cleanup_path = str(cleanup_request.get("path") or "").replace("${{order_id}}", "{order_id}")
        references.append(_reference(locator=f"{cleanup_method} {cleanup_path}"))
    return {
        "id": case_id,
        "title": case_id,
        "priority": "P0",
        "contract_status": "confirmed",
        "business_rule_refs": ["ORDER-001"],
        "review_status": "needs_human_review",
        "review_questions": ["confirm fixtures"],
        "source_refs": references,
        "pending": [],
        "request": {
            "method": method,
            "path": path,
            "headers": {},
            "query": {},
            "body": {} if body is None else body,
        },
        "assertions": assertions or [{"type": "status_code", "expected": 200}],
        "variables": variables or {},
        "cleanup": cleanup or [],
    }


def _draft(*cases: dict[str, Any]) -> ApiTestCasesDraft:
    return ApiTestCasesDraft.model_validate(
        {
            "schema_version": "agentic-qa.api-cases.v1.1",
            "artifact_type": "api_automation_cases",
            "status": "needs_human_review",
            "human_review_required": True,
            "base_url_env": "AGENTIC_QA_BASE_URL",
            "business_rules": ["ORDER-001"],
            "source_refs": [_reference()],
            "cases": list(cases),
            "review_questions": ["confirm environment"],
        }
    )


def _path_contract(*, source: str = SOURCE):
    return inspect_openapi(
        {
            "openapi": "3.1.0",
            "info": {"title": "Orders", "version": "1"},
            "paths": {
                "/orders/{order_id}": {
                    "parameters": [
                        {
                            "name": "order_id",
                            "in": "path",
                            "required": True,
                            "schema": {
                                "type": "string",
                                "enum": ["ORD-001", "ORD-002"],
                                "pattern": "^ORD-[0-9]{3}$",
                            },
                        }
                    ],
                    "get": {
                        "responses": {
                            "200": {
                                "description": "found",
                                "headers": {"X-Item-Count": {"schema": {"type": "integer"}}},
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "data": {
                                                    "type": "object",
                                                    "properties": {
                                                        "id": {"type": "string"},
                                                        "count": {"type": "integer"},
                                                    },
                                                }
                                            },
                                        }
                                    }
                                },
                            }
                        }
                    },
                    "delete": {"responses": {"204": {"description": "deleted"}}},
                }
            },
        },
        source=source,
    )


def test_path_parameter_and_cleanup_validate_for_each_dataset() -> None:
    case = _case(
        variables={
            "datasets": [
                {"id": "first", "values": {"order_id": "ORD-001"}},
                {"id": "second", "values": {"order_id": "ORD-002"}},
            ]
        },
        assertions=[
            {"type": "status_code", "expected": 200},
            {"type": "json_field_equals", "path": "$.data.count", "expected": 2},
            {"type": "header_equals", "path": "x-item-count", "expected": "2"},
        ],
        cleanup=[
            {
                "id": "delete",
                "request": {
                    "method": "DELETE",
                    "path": "/orders/${{order_id}}",
                },
                "assertions": [{"type": "status_code", "expected": 204}],
            }
        ],
    )

    result = validate_api_contracts(_draft(case), [_path_contract()])

    assert result.issues == ()
    assert result.semantic_rate == 1


def test_dataset_schema_failure_identifies_only_the_invalid_instance() -> None:
    case = _case(
        variables={
            "datasets": [
                {"id": "valid", "values": {"order_id": "ORD-001"}},
                {"id": "invalid", "values": {"order_id": "bad"}},
            ]
        }
    )

    result = validate_api_contracts(_draft(case), [_path_contract()])

    assert {issue.code for issue in result.issues} == {"schema_mismatch"}
    assert {issue.instance_id for issue in result.issues} == {"API-001::invalid"}
    assert {issue.location for issue in result.issues} == {"request.path.order_id"}


def test_openapi_source_locator_must_use_method_and_contract_path() -> None:
    case = _case(source_refs=[_reference(locator="http://orders/ORD-001")])

    result = validate_api_contracts(_draft(case), [_path_contract()])

    assert {issue.code for issue in result.issues} == {"source_locator_mismatch"}
    assert result.issues[0].message == (
        "OpenAPI source locator must be exactly 'GET /orders/{order_id}'"
    )


def test_dataset_expansion_preserves_native_json_types_and_schema_constraints() -> None:
    inspection = inspect_openapi(
        {
            "openapi": "3.1.0",
            "info": {"title": "Create order", "version": "1"},
            "paths": {
                "/orders": {
                    "post": {
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "allOf": [
                                            {
                                                "type": "object",
                                                "required": ["quantity", "active"],
                                            },
                                            {
                                                "type": "object",
                                                "additionalProperties": False,
                                                "properties": {
                                                    "quantity": {
                                                        "type": "integer",
                                                        "minimum": 1,
                                                        "maximum": 5,
                                                    },
                                                    "active": {"type": "boolean"},
                                                    "weight": {"type": "number"},
                                                    "metadata": {"type": "object"},
                                                    "tags": {
                                                        "type": "array",
                                                        "minItems": 1,
                                                        "uniqueItems": True,
                                                        "items": {"type": "string"},
                                                    },
                                                    "choice": {
                                                        "oneOf": [
                                                            {"const": "standard"},
                                                            {"const": "express"},
                                                        ]
                                                    },
                                                },
                                            },
                                        ]
                                    }
                                }
                            },
                        },
                        "responses": {"201": {"description": "created"}},
                    }
                }
            },
        },
        source=SOURCE,
    )
    body = {
        "quantity": "${{quantity}}",
        "active": "${{active}}",
        "weight": "${{weight}}",
        "metadata": "${{metadata}}",
        "tags": "${{tags}}",
        "choice": "${{choice}}",
    }
    case = _case(
        method="POST",
        path="/orders",
        body=body,
        assertions=[{"type": "status_code", "expected": 201}],
        variables={
            "datasets": [
                {
                    "id": "valid",
                    "values": {
                        "quantity": 2,
                        "active": True,
                        "weight": 1.5,
                        "metadata": {"fixture": "safe"},
                        "tags": ["one", "two"],
                        "choice": "standard",
                    },
                },
                {
                    "id": "invalid",
                    "values": {
                        "quantity": 9,
                        "active": "true",
                        "weight": 1.5,
                        "metadata": {"fixture": "safe"},
                        "tags": ["same", "same"],
                        "choice": "unsupported",
                    },
                },
            ]
        },
    )

    result = validate_api_contracts(_draft(case), [inspection])

    assert result.issues
    assert {issue.instance_id for issue in result.issues} == {"API-001::invalid"}
    assert all(issue.code == "schema_mismatch" for issue in result.issues)


def test_string_interpolation_accepts_scalars_and_rejects_composite_values() -> None:
    inspection = inspect_openapi(
        {
            "openapi": "3.1.0",
            "info": {"title": "Labels", "version": "1"},
            "paths": {
                "/labels": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["label"],
                                        "properties": {
                                            "label": {
                                                "type": "string",
                                                "pattern": "^order-[0-9]+$",
                                            }
                                        },
                                    }
                                }
                            }
                        },
                        "responses": {"201": {"description": "created"}},
                    }
                }
            },
        },
        source=SOURCE,
    )
    valid = _case(
        method="POST",
        path="/labels",
        body={"label": "order-${{value}}"},
        assertions=[{"type": "status_code", "expected": 201}],
        variables={"datasets": [{"id": "valid", "values": {"value": 12}}]},
    )
    invalid = _case(
        method="POST",
        path="/labels",
        body={"label": "order-${{value}}"},
        assertions=[{"type": "status_code", "expected": 201}],
        variables={"datasets": [{"id": "invalid", "values": {"value": {"id": 12}}}]},
    )

    assert validate_api_contracts(_draft(valid), [inspection]).issues == ()
    invalid_result = validate_api_contracts(_draft(invalid), [inspection])

    assert [issue.code for issue in invalid_result.issues] == ["non_scalar_interpolation"]


def test_upstream_extraction_defers_unknown_leaf_type_but_checks_source() -> None:
    creator_contract = inspect_openapi(
        {
            "openapi": "3.1.0",
            "info": {"title": "Orders", "version": "1"},
            "paths": {
                "/orders": {
                    "post": {
                        "responses": {
                            "201": {
                                "description": "created",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "data": {
                                                    "type": "object",
                                                    "properties": {"id": {"type": "string"}},
                                                }
                                            },
                                        }
                                    }
                                },
                            }
                        }
                    }
                }
            },
        },
        source=SOURCE,
    )
    creator = _case(
        case_id="API-CREATE",
        method="POST",
        path="/orders",
        assertions=[{"type": "status_code", "expected": 201}],
        variables={
            "extract": {
                "order_id": {
                    "source": "response_json",
                    "path": "$.data.id",
                    "required": True,
                }
            }
        },
    )
    reader = _case(case_id="API-READ")

    result = validate_api_contracts(_draft(creator, reader), [creator_contract, _path_contract()])

    assert result.issues == ()


def test_embedded_and_ambiguous_path_templates_are_rejected() -> None:
    embedded = inspect_openapi(
        {
            "openapi": "3.1.0",
            "info": {"title": "Files", "version": "1"},
            "paths": {
                "/files/{id}.json": {"get": {"responses": {"200": {"description": "found"}}}}
            },
        },
        source=SOURCE,
    )
    embedded_case = _case(
        path="/files/${{file_id}}.json",
        variables={"datasets": [{"id": "one", "values": {"file_id": "1"}}]},
    )

    embedded_result = validate_api_contracts(_draft(embedded_case), [embedded])

    assert [issue.code for issue in embedded_result.issues] == ["operation_not_found"]

    literal_case = _case(path="/orders/ORD-001", source_refs=[_reference()])
    literal_result = validate_api_contracts(_draft(literal_case), [_path_contract()])

    assert [issue.code for issue in literal_result.issues] == ["path_parameter_requires_variable"]

    second_source = "sources/orders-copy.openapi.yml"
    ambiguous_case = _case(
        variables={"datasets": [{"id": "one", "values": {"order_id": "ORD-001"}}]},
        source_refs=[_reference(), _reference(second_source)],
    )
    ambiguous_result = validate_api_contracts(
        _draft(ambiguous_case),
        [_path_contract(), _path_contract(source=second_source)],
    )

    assert [issue.code for issue in ambiguous_result.issues] == ["ambiguous_operation"]
