from __future__ import annotations

import re
from typing import Any

import yaml
from pydantic import ValidationError

from runtime.schemas.api_test_cases import (
    API_CASES_SCHEMA_VERSION,
    ApiTestCasesDraft,
)

SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key|secret|token|cookie)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
]


def _contains_secret(content: str) -> bool:
    return any(pattern.search(content) for pattern in SECRET_PATTERNS)


def _structure_errors(data: dict[str, Any]) -> list[str]:
    try:
        ApiTestCasesDraft.model_validate(data)
    except ValidationError as exc:
        return [
            "接口 YAML 用例草稿结构错误: "
            + ".".join(str(part) for part in error["loc"])
            + f" {error['msg']}"
            for error in exc.errors()
        ]
    return []


def validate_api_test_cases_yaml(
    content: str,
    *,
    schema_version: str = API_CASES_SCHEMA_VERSION,
) -> list[str]:
    errors: list[str] = []
    if not content.strip():
        return ["接口 YAML 用例草稿为空。"]
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return [f"接口 YAML 用例草稿不是合法 YAML: {exc}"]
    if not isinstance(data, dict):
        return ["接口 YAML 用例草稿必须是 YAML mapping。"]

    errors.extend(_structure_errors(data))
    if data.get("schema_version") != schema_version:
        errors.append("接口 YAML 用例草稿 schema_version 不正确。")
    if data.get("status") != "needs_human_review":
        errors.append("接口 YAML 用例草稿候选状态必须是 needs_human_review。")
    if data.get("human_review_required") is not True:
        errors.append("接口 YAML 用例草稿必须要求人工审核。")
    if data.get("base_url_env") != "AGENTIC_QA_BASE_URL":
        errors.append("接口 YAML 用例草稿必须通过 AGENTIC_QA_BASE_URL 读取环境。")
    source_refs = data.get("source_refs")
    if not isinstance(source_refs, list) or not source_refs:
        errors.append("接口 YAML 用例草稿必须包含顶层 source_refs。")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("接口 YAML 用例草稿必须包含 cases。")
        return errors
    business_rules = data.get("business_rules")
    if not isinstance(business_rules, list) or not business_rules:
        errors.append("接口 YAML 用例草稿必须包含 business_rules。")
    required_fields = {
        "id",
        "title",
        "contract_status",
        "business_rule_refs",
        "review_status",
        "review_questions",
        "source_refs",
        "pending",
    }
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            errors.append(f"接口 YAML 用例第 {index} 条必须是 mapping。")
            continue
        missing = sorted(required_fields - set(case))
        if missing:
            errors.append(f"接口 YAML 用例第 {index} 条缺少字段: {', '.join(missing)}")
        case_source_refs = case.get("source_refs")
        if not isinstance(case_source_refs, list) or not case_source_refs:
            errors.append(f"接口 YAML 用例第 {index} 条必须包含 source_refs。")
            case_source_refs = []
        if case.get("review_status") != "needs_human_review":
            errors.append(f"接口 YAML 用例第 {index} 条 review_status 必须是 needs_human_review。")
        contract_status = str(case.get("contract_status") or "")
        source_types = {
            str(ref.get("source_type") or "") for ref in case_source_refs if isinstance(ref, dict)
        }
        review_questions = case.get("review_questions")
        if not isinstance(review_questions, list) or not review_questions:
            errors.append(f"接口 YAML 用例第 {index} 条必须包含 review_questions。")
        if contract_status not in {"missing", "pending_confirmation", "confirmed"}:
            errors.append(
                f"接口 YAML 用例第 {index} 条 contract_status 必须是 "
                "missing/pending_confirmation/confirmed。"
            )
        if contract_status == "missing":
            if "method" in case or "path" in case:
                errors.append(
                    f"接口 YAML 用例第 {index} 条 contract_status=missing 时不得包含 method/path。"
                )
            request = case.get("request", {})
            if request != {}:
                errors.append(
                    f"接口 YAML 用例第 {index} 条 contract_status=missing 时 request 只能是 {{}}。"
                )
            expected = case.get("expected", {})
            if isinstance(expected, dict) and (
                "status_code" in expected or "json_contains_keys" in expected
            ):
                errors.append(
                    f"接口 YAML 用例第 {index} 条 contract_status=missing 时不得包含 "
                    "expected.status_code/json_contains_keys。"
                )
        elif contract_status == "pending_confirmation":
            if "api_discovery_report" not in source_types:
                errors.append(
                    f"接口 YAML 用例第 {index} 条 contract_status=pending_confirmation "
                    "必须包含 api_discovery_report 来源。"
                )
            for ref in case_source_refs:
                if isinstance(ref, dict) and str(ref.get("confidence") or "") == "high":
                    errors.append(
                        f"接口 YAML 用例第 {index} 条 contract_status=pending_confirmation "
                        "confidence 不得为 high。"
                    )
        elif contract_status == "confirmed":
            if not ({"swagger", "openapi", "apifox"} & source_types):
                errors.append(
                    f"接口 YAML 用例第 {index} 条 contract_status=confirmed "
                    "必须包含 swagger/openapi/apifox 来源。"
                )
            for field in ("method", "path", "request", "expected"):
                if field not in case:
                    errors.append(
                        f"接口 YAML 用例第 {index} 条 contract_status=confirmed 缺少字段: {field}"
                    )
            expected = case.get("expected")
            if not isinstance(expected, dict) or not expected.get("status_code"):
                errors.append(f"接口 YAML 用例第 {index} 条缺少 expected.status_code。")
        if str(case.get("path") or "").startswith("http"):
            errors.append(f"接口 YAML 用例第 {index} 条 path 不得写完整环境域名。")
    if _contains_secret(content):
        errors.append("接口 YAML 用例草稿疑似包含真实 token / cookie / 密钥。")
    return errors
