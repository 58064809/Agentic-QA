from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)}")


@dataclass(frozen=True)
class ApiCase:
    id: str
    title: str
    method: str
    path: str
    request: dict[str, Any]
    expected: dict[str, Any]


@dataclass(frozen=True)
class ApiCaseResult:
    case_id: str
    title: str
    status_code: int
    passed: bool


def load_api_cases(path: Path | str) -> list[ApiCase]:
    source = Path(path)
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"接口 YAML 用例必须是 mapping: {source.as_posix()}")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"接口 YAML 用例缺少 cases: {source.as_posix()}")
    parsed: list[ApiCase] = []
    for index, item in enumerate(cases, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"接口 YAML 用例第 {index} 条必须是 mapping")
        parsed.append(
            ApiCase(
                id=str(item.get("id") or f"API-{index:03d}"),
                title=str(item.get("title") or item.get("id") or f"API case {index}"),
                method=str(item.get("method") or "GET").upper(),
                path=str(item.get("path") or "/"),
                request=dict(item.get("request") or {}),
                expected=dict(item.get("expected") or {}),
            )
        )
    return parsed


def _resolve_env_placeholders(value: Any, env: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return ENV_PLACEHOLDER_RE.sub(lambda match: env.get(match.group(1), ""), value)
    if isinstance(value, list):
        return [_resolve_env_placeholders(item, env) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_env_placeholders(item, env) for key, item in value.items()}
    return value


def _expected_status_codes(expected: Mapping[str, Any]) -> set[int]:
    raw = expected.get("status_code", [])
    if isinstance(raw, int):
        return {raw}
    if isinstance(raw, list):
        return {int(item) for item in raw}
    return set()


def execute_api_case(
    case: ApiCase,
    *,
    base_url: str,
    env: Mapping[str, str] | None = None,
    request_func: Callable[..., Any] | None = None,
) -> ApiCaseResult:
    if not base_url:
        raise ValueError("base_url 不能为空")
    if case.path.startswith("http://") or case.path.startswith("https://"):
        raise ValueError("接口 YAML 用例 path 不得包含完整环境域名")
    env = env or os.environ
    request = _resolve_env_placeholders(case.request, env)
    headers = dict(request.get("headers") or {})
    params = request.get("params")
    json_body = request.get("json")
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
    expected_codes = _expected_status_codes(case.expected)
    assert response.status_code in expected_codes, (
        f"{case.id} HTTP 状态码不符合预期: actual={response.status_code}, "
        f"expected={sorted(expected_codes)}"
    )
    expected_keys = case.expected.get("json_contains_keys")
    if expected_keys:
        body = response.json()
        missing = [key for key in expected_keys if key not in body]
        assert not missing, f"{case.id} 响应 JSON 缺少字段: {missing}"
    return ApiCaseResult(
        case_id=case.id,
        title=case.title,
        status_code=int(response.status_code),
        passed=True,
    )
