from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from runtime.schemas.api_test_cases import API_CASES_SCHEMA_VERSION

ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)}")


@dataclass(frozen=True)
class ApiCase:
    id: str
    title: str
    request: dict[str, Any]
    assertions: list[dict[str, Any]]

    @property
    def method(self) -> str:
        return str(self.request.get("method") or "GET").upper()

    @property
    def path(self) -> str:
        return str(self.request.get("path") or "/")


@dataclass(frozen=True)
class ApiCaseResult:
    case_id: str
    title: str
    status_code: int
    passed: bool


def _normalize_case(item: dict[str, Any], index: int) -> ApiCase:
    request = dict(item.get("request") or {})
    assertions = [dict(value) for value in item.get("assertions") or [] if isinstance(value, dict)]
    return ApiCase(
        id=str(item.get("id") or f"API-{index:03d}"),
        title=str(item.get("title") or item.get("id") or f"API case {index}"),
        request=request,
        assertions=assertions,
    )


def load_api_cases(path: Path | str) -> list[ApiCase]:
    source = Path(path)
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"接口 YAML 用例必须是 mapping: {source.as_posix()}")
    schema_version = str(data.get("schema_version") or "")
    if schema_version != API_CASES_SCHEMA_VERSION:
        raise ValueError(
            "接口 YAML schema_version 必须是 "
            f"{API_CASES_SCHEMA_VERSION}: {schema_version or '<missing>'}"
        )
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"接口 YAML 用例缺少 cases: {source.as_posix()}")
    parsed: list[ApiCase] = []
    for index, item in enumerate(cases, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"接口 YAML 用例第 {index} 条必须是 mapping")
        parsed.append(_normalize_case(item, index))
    return parsed


def _resolve_env_placeholders(value: Any, env: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return ENV_PLACEHOLDER_RE.sub(lambda match: env.get(match.group(1), ""), value)
    if isinstance(value, list):
        return [_resolve_env_placeholders(item, env) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_env_placeholders(item, env) for key, item in value.items()}
    return value


def _status_codes(assertions: list[dict[str, Any]]) -> set[int]:
    for assertion in assertions:
        if assertion.get("type") != "status_code":
            continue
        expected = assertion.get("expected")
        if isinstance(expected, int):
            return {expected}
        if isinstance(expected, list):
            return {int(value) for value in expected}
    return set()


def _json_path_exists(body: Any, path: str) -> bool:
    if not path.startswith("$."):
        return False
    current = body
    for part in path[2:].split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def execute_api_case(
    case: ApiCase,
    *,
    base_url: str,
    env: Mapping[str, str] | None = None,
    request_func: Callable[..., Any] | None = None,
) -> ApiCaseResult:
    if not base_url:
        raise ValueError("base_url 不能为空")
    if case.path.startswith(("http://", "https://")):
        raise ValueError("接口 YAML 用例 path 不得包含完整环境域名")
    env = env or os.environ
    request = _resolve_env_placeholders(case.request, env)
    headers = dict(request.get("headers") or {})
    params = request.get("query")
    json_body = request.get("body")
    if request_func is None:
        import requests

        request_func = requests.request
    response = request_func(
        case.method,
        base_url.rstrip("/") + "/" + case.path.lstrip("/"),
        headers=headers,
        params=params,
        json=json_body,
        timeout=int(request.get("timeout") or 10),
    )
    expected_codes = _status_codes(case.assertions)
    if not expected_codes:
        raise ValueError(f"{case.id} 缺少 status_code assertion，不能执行")
    assert response.status_code in expected_codes, (
        f"{case.id} HTTP 状态码不符合预期: actual={response.status_code}, "
        f"expected={sorted(expected_codes)}"
    )
    body: Any | None = None
    for assertion in case.assertions:
        if assertion.get("type") != "json_field_exists":
            continue
        body = response.json() if body is None else body
        path = str(assertion.get("path") or "")
        assert _json_path_exists(body, path), f"{case.id} 响应 JSON 缺少字段: {path}"
    return ApiCaseResult(
        case_id=case.id,
        title=case.title,
        status_code=int(response.status_code),
        passed=True,
    )
