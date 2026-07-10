from __future__ import annotations

import re
from typing import Any

import yaml
from pydantic import ValidationError

from runtime.schemas.api_test_cases import API_CASES_SCHEMA_VERSION, ApiTestCasesDraft

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


def _request_method_path(case: dict[str, Any]) -> tuple[str, str]:
    request = case.get("request")
    if not isinstance(request, dict):
        return "", ""
    return str(request.get("method") or ""), str(request.get("path") or "")


def _has_status_assertion(assertions: Any) -> bool:
    return isinstance(assertions, list) and any(
        isinstance(item, dict)
        and item.get("type") == "status_code"
        and (
            isinstance(item.get("expected"), int)
            or (
                isinstance(item.get("expected"), list)
                and bool(item.get("expected"))
                and all(isinstance(value, int) for value in item["expected"])
            )
        )
        for item in assertions
    )


def validate_api_test_cases_yaml(
    content: str,
    *,
    schema_version: str = API_CASES_SCHEMA_VERSION,
) -> list[str]:
    if not content.strip():
        return ["接口 YAML 用例草稿为空。"]
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return [f"接口 YAML 用例草稿不是合法 YAML: {exc}"]
    if not isinstance(data, dict):
        return ["接口 YAML 用例草稿必须是 YAML mapping。"]

    errors = _structure_errors(data)
    if data.get("schema_version") != schema_version:
        errors.append("接口 YAML 用例草稿 schema_version 不正确。")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        return [*errors, "接口 YAML 用例草稿必须包含 cases。"]

    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            continue
        contract_status = str(case.get("contract_status") or "")
        request = case.get("request")
        assertions = case.get("assertions")
        method, path = _request_method_path(case)
        refs = case.get("source_refs")
        source_types = {
            str(ref.get("source_type") or "") for ref in refs or [] if isinstance(ref, dict)
        }

        if contract_status == "missing":
            if request != {}:
                errors.append(
                    f"接口 YAML 用例第 {index} 条 contract_status=missing 时 request 只能是 {{}}。"
                )
            if assertions != []:
                errors.append(
                    f"接口 YAML 用例第 {index} 条 contract_status=missing 时 assertions 只能是 []。"
                )
        elif contract_status == "pending_confirmation":
            if "api_discovery_report" not in source_types:
                errors.append(
                    f"接口 YAML 用例第 {index} 条 contract_status=pending_confirmation "
                    "必须包含 api_discovery_report 来源。"
                )
            if not method or not path:
                errors.append(
                    f"接口 YAML 用例第 {index} 条运行时接口候选必须包含 request.method/path。"
                )
            if assertions != []:
                errors.append(
                    f"接口 YAML 用例第 {index} 条待确认接口不得包含确定性 assertions。"
                )
            for ref in refs or []:
                if isinstance(ref, dict) and ref.get("confidence") == "high":
                    errors.append(
                        f"接口 YAML 用例第 {index} 条 contract_status=pending_confirmation "
                        "confidence 不得为 high。"
                    )
        elif contract_status == "partial":
            if not ({"api_document", "swagger", "openapi", "apifox"} & source_types):
                errors.append(
                    f"接口 YAML 用例第 {index} 条 contract_status=partial 必须包含接口文档来源。"
                )
            if not method or not path:
                errors.append(
                    f"接口 YAML 用例第 {index} 条 partial 契约必须包含 request.method/path。"
                )
        elif contract_status == "confirmed":
            if not ({"swagger", "openapi", "apifox"} & source_types):
                errors.append(
                    f"接口 YAML 用例第 {index} 条 contract_status=confirmed "
                    "必须包含 swagger/openapi/apifox 来源。"
                )
            if not method or not path:
                errors.append(
                    f"接口 YAML 用例第 {index} 条 confirmed 契约缺少 request.method/path。"
                )
            if not _has_status_assertion(assertions):
                errors.append(f"接口 YAML 用例第 {index} 条缺少 status_code assertion。")
        if path.startswith(("http://", "https://")):
            errors.append(f"接口 YAML 用例第 {index} 条 request.path 不得写完整环境域名。")
        elif path and not path.startswith("/"):
            errors.append(f"接口 YAML 用例第 {index} 条 request.path 必须是以 / 开头的相对路径。")
        if method and method.upper() not in {
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "HEAD",
            "OPTIONS",
            "TRACE",
        }:
            errors.append(f"接口 YAML 用例第 {index} 条 request.method 不是受支持的 HTTP 方法。")

    if _contains_secret(content):
        errors.append("接口 YAML 用例草稿疑似包含真实 token / cookie / 密钥。")
    return errors
