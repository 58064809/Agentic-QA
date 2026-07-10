from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.schemas.api_test_cases import ApiTestCasesDraft  # noqa: E402
from runtime.validators.api_case_contract_rules import validate_api_test_cases_yaml  # noqa: E402


def _source_ref(source_type: str, *, confidence: str = "high") -> dict:
    return {
        "source_type": source_type,
        "source_path": "knowledge/api/product/openapi.json",
        "chunk_id": "openapi.product.GET.abc123",
        "locator": "GET /product/detail",
        "summary": "查询商品详情",
        "confidence": confidence,
    }


def _payload(case: dict) -> dict:
    return {
        "schema_version": "agentic-qa.api-cases.v1.1",
        "artifact_type": "api_automation_cases",
        "status": "needs_human_review",
        "human_review_required": True,
        "base_url_env": "AGENTIC_QA_BASE_URL",
        "business_rules": ["用户可查询商品详情"],
        "source_refs": [_source_ref("openapi")],
        "cases": [case],
        "review_questions": ["请确认测试数据。"],
    }


def _base_case(**overrides: object) -> dict:
    case = {
        "id": "API-001-SUCCESS",
        "title": "查询商品详情成功",
        "priority": "P0",
        "contract_status": "confirmed",
        "review_status": "needs_human_review",
        "business_rule_refs": ["用户可查询商品详情"],
        "source_refs": [_source_ref("openapi")],
        "request": {
            "method": "GET",
            "path": "/product/detail",
            "query": {"commodityId": "${TEST_COMMODITY_ID}"},
        },
        "assertions": [
            {"type": "status_code", "expected": [200]},
            {"type": "json_field_exists", "path": "$.data"},
        ],
        "variables": {"env": ["TEST_COMMODITY_ID"]},
        "cleanup": [],
        "pending": ["确认测试数据"],
        "review_questions": ["请确认测试数据。"],
    }
    case.update(overrides)
    return case


def test_api_test_cases_schema_accepts_confirmed_payload():
    payload = _payload(_base_case())

    model = ApiTestCasesDraft.model_validate(payload)

    assert model.schema_version == "agentic-qa.api-cases.v1.1"
    assert model.cases
    assert model.cases[0].contract_status == "confirmed"
    assert validate_api_test_cases_yaml(yaml.safe_dump(payload, allow_unicode=True)) == []


def test_validator_rejects_missing_contract_method_path_and_field_facts():
    payload = _payload(
        _base_case(
            contract_status="missing",
            source_refs=[_source_ref("prd", confidence="low")],
            request={
                "method": "POST",
                "path": "/待确认-url",
                "body": {"field": "待确认请求字段"},
            },
            assertions=[{"type": "status_code", "expected": [200]}],
            review_questions=["请补充 Swagger / OpenAPI / Apifox 接口契约。"],
        )
    )

    errors = validate_api_test_cases_yaml(yaml.safe_dump(payload, allow_unicode=True))

    assert any("request 只能是 {}" in error for error in errors)
    assert any("assertions 只能是 []" in error for error in errors)


def test_validator_requires_discovery_source_for_pending_confirmation():
    payload = _payload(
        _base_case(
            contract_status="pending_confirmation",
            source_refs=[_source_ref("prd", confidence="medium")],
            request={"method": "POST", "path": "/captured"},
            assertions=[],
            review_questions=["请使用 Swagger / OpenAPI / Apifox 核对该 method/path。"],
        )
    )

    errors = validate_api_test_cases_yaml(yaml.safe_dump(payload, allow_unicode=True))

    assert any("必须包含 api_discovery_report 来源" in error for error in errors)


def test_validator_rejects_high_confidence_for_pending_confirmation():
    payload = _payload(
        _base_case(
            contract_status="pending_confirmation",
            source_refs=[_source_ref("api_discovery_report", confidence="high")],
            request={"method": "POST", "path": "/captured"},
            assertions=[],
            review_questions=["请使用 Swagger / OpenAPI / Apifox 核对该 method/path。"],
        )
    )

    errors = validate_api_test_cases_yaml(yaml.safe_dump(payload, allow_unicode=True))

    assert any("confidence 不得为 high" in error for error in errors)


def test_validator_requires_openapi_family_source_for_confirmed_contract():
    payload = _payload(
        _base_case(source_refs=[_source_ref("api_discovery_report", confidence="medium")])
    )

    errors = validate_api_test_cases_yaml(yaml.safe_dump(payload, allow_unicode=True))

    assert any("必须包含 swagger/openapi/apifox 来源" in error for error in errors)


def test_validator_rejects_status_assertion_without_expected_codes():
    payload = _payload(
        _base_case(assertions=[{"type": "status_code"}])
    )

    errors = validate_api_test_cases_yaml(yaml.safe_dump(payload, allow_unicode=True))

    assert any("缺少 status_code assertion" in error for error in errors)
