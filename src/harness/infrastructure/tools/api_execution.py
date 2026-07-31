from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from harness.domain.models import (
    ApiAuthentication,
    ApiTokenInjection,
    ExecutionProfile,
    LoginApiAuthentication,
    StaticTokenApiAuthentication,
)
from harness.domain.schemas.api_test_cases import API_CASES_SCHEMA_VERSION, ApiTestCase
from harness.domain.schemas.execution_evidence import (
    EXECUTION_EVIDENCE_SCHEMA_VERSION,
    AssertionEvidence,
    CaseExecutionEvidence,
    ExecutionEnvironment,
    ExecutionEvidence,
    ExecutionSummary,
)

ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)}")
URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
UTC = timezone.utc


def _resolve(value: Any, env: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return ENV_PLACEHOLDER_RE.sub(lambda match: env.get(match.group(1), ""), value)
    if isinstance(value, list):
        return [_resolve(item, env) for item in value]
    if isinstance(value, dict):
        return {key: _resolve(item, env) for key, item in value.items()}
    return value


def _required_environment_references(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(ENV_PLACEHOLDER_RE.findall(value))
    if isinstance(value, list):
        return set().union(*(_required_environment_references(item) for item in value), set())
    if isinstance(value, dict):
        return set().union(
            *(_required_environment_references(item) for item in value.values()), set()
        )
    return set()


def _resolve_required(value: Any, env: Mapping[str, str]) -> Any:
    missing = sorted(name for name in _required_environment_references(value) if not env.get(name))
    if missing:
        raise RuntimeError(
            "API authentication is missing environment values: " + ", ".join(missing)
        )
    return _resolve(value, env)


def _json_path_exists(body: Any, path: str) -> bool:
    if not path.startswith("$."):
        return False
    current = body
    for part in path[2:].split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _json_path_value(body: Any, path: str) -> Any:
    current = body
    for part in path[2:].split("."):
        if not isinstance(current, dict) or part not in current:
            raise RuntimeError(f"API login response does not contain token path: {path}")
        current = current[part]
    return current


def _sanitize_error(error: Exception, secrets: list[str]) -> str:
    message = URL_RE.sub("<redacted-url>", str(error))
    for secret in secrets:
        if secret:
            message = message.replace(secret, "<redacted>")
    return message[:1000]


def _injected_header(injection: ApiTokenInjection, token: str) -> tuple[str, str]:
    value = f"{injection.prefix} {token}" if injection.prefix else token
    return injection.name, value


def _authenticate(
    auth: ApiAuthentication | None,
    *,
    base_url: str,
    profile: ExecutionProfile,
    env: Mapping[str, str],
    request_func: Callable[..., Any],
) -> tuple[tuple[str, str] | None, list[str]]:
    if auth is None:
        return None, []
    if isinstance(auth, StaticTokenApiAuthentication):
        token = (
            auth.token.get_secret_value().strip()
            if auth.token is not None
            else env.get(str(auth.token_env), "").strip()
        )
        if not token:
            raise RuntimeError(
                f"API authentication token environment variable is not set: {auth.token_env}"
            )
        return _injected_header(auth.injection, token), [token]
    if not isinstance(auth, LoginApiAuthentication):
        raise TypeError(f"unsupported API authentication configuration: {type(auth).__name__}")
    if auth.request.method not in profile.allowed_http_methods:
        raise PermissionError(
            f"API login method {auth.request.method} is not allowed by execution profile"
        )
    request = _resolve_required(auth.request.model_dump(mode="python"), env)
    try:
        response = request_func(
            auth.request.method,
            base_url.rstrip("/") + "/" + auth.request.path.lstrip("/"),
            headers=dict(request.get("headers") or {}),
            params=request.get("query"),
            json=request.get("body"),
            timeout=profile.request_timeout_seconds,
        )
        if int(response.status_code) not in set(auth.expected_status_codes):
            raise RuntimeError(f"API login returned HTTP {int(response.status_code)}")
        body = response.json()
        token = _json_path_value(body, auth.token_json_path)
        if not isinstance(token, str) or not token.strip():
            raise RuntimeError("API login response token must be a non-empty string")
        token = token.strip()
        return _injected_header(auth.injection, token), [token]
    except Exception as exc:
        message = _sanitize_error(exc, [base_url, *env.values()])
        raise RuntimeError(f"API authentication failed: {message}") from exc


def _apply_authentication_header(
    headers: dict[str, Any],
    authentication_header: tuple[str, str] | None,
) -> dict[str, Any]:
    if authentication_header is None:
        return headers
    name, value = authentication_header
    result = {key: item for key, item in headers.items() if key.casefold() != name.casefold()}
    result[name] = value
    return result


def _execute_case(
    case: ApiTestCase,
    *,
    base_url: str,
    profile: ExecutionProfile,
    env: Mapping[str, str],
    request_func: Callable[..., Any],
    authentication_header: tuple[str, str] | None,
    authentication_secrets: list[str],
) -> CaseExecutionEvidence:
    method = str(case.request.method or "").upper()
    path = str(case.request.path or "")
    started_at = datetime.now(tz=UTC)
    started_clock = perf_counter()
    if case.contract_status != "confirmed" or not method or not path:
        return CaseExecutionEvidence(
            case_id=case.id,
            title=case.title,
            method=method,
            path=path,
            status="blocked",
            started_at=started_at,
            completed_at=datetime.now(tz=UTC),
            duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
            error="API contract is not confirmed",
        )
    if path.startswith(("http://", "https://")):
        raise ValueError("API case path must be relative")
    if method not in profile.allowed_http_methods:
        return CaseExecutionEvidence(
            case_id=case.id,
            title=case.title,
            method=method,
            path=path,
            status="blocked",
            started_at=started_at,
            completed_at=datetime.now(tz=UTC),
            duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
            error=f"HTTP method {method} is not allowed by execution profile",
        )
    try:
        request = _resolve(case.request.model_dump(mode="python"), env)
        headers = _apply_authentication_header(
            dict(request.get("headers") or {}),
            authentication_header,
        )
        response = request_func(
            method,
            base_url.rstrip("/") + "/" + path.lstrip("/"),
            headers=headers,
            params=request.get("query"),
            json=request.get("body"),
            timeout=profile.request_timeout_seconds,
        )
        evidence: list[AssertionEvidence] = []
        body: Any | None = None
        for assertion in case.assertions:
            if assertion.type == "status_code":
                expected = assertion.expected
                codes = (
                    {int(item) for item in expected}
                    if isinstance(expected, list)
                    else {int(expected)}
                )
                actual = int(response.status_code)
                evidence.append(
                    AssertionEvidence(
                        type=assertion.type,
                        passed=actual in codes,
                        expected=sorted(codes),
                        actual=actual,
                    )
                )
            elif assertion.type == "json_field_exists":
                body = response.json() if body is None else body
                passed = _json_path_exists(body, assertion.path or "")
                evidence.append(
                    AssertionEvidence(
                        type=assertion.type,
                        passed=passed,
                        expected=True,
                        actual=passed,
                        path=assertion.path,
                    )
                )
            else:
                evidence.append(
                    AssertionEvidence(
                        type=assertion.type,
                        passed=False,
                        expected=assertion.expected,
                        path=assertion.path,
                        message="unsupported assertion type",
                    )
                )
        status = "passed" if evidence and all(item.passed for item in evidence) else "failed"
        return CaseExecutionEvidence(
            case_id=case.id,
            title=case.title,
            method=method,
            path=path,
            status=status,
            started_at=started_at,
            completed_at=datetime.now(tz=UTC),
            duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
            status_code=int(response.status_code),
            assertions=evidence,
            error=None if status == "passed" else "one or more assertions failed",
        )
    except Exception as exc:
        return CaseExecutionEvidence(
            case_id=case.id,
            title=case.title,
            method=method,
            path=path,
            status="error",
            started_at=started_at,
            completed_at=datetime.now(tz=UTC),
            duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
            error=_sanitize_error(
                exc,
                [base_url, *env.values(), *authentication_secrets],
            ),
        )


def execute_api_cases(
    cases: list[ApiTestCase],
    *,
    run_id: str,
    source_cases_path: str,
    profile: ExecutionProfile,
    env: Mapping[str, str] | None = None,
    request_func: Callable[..., Any] | None = None,
    authentication: ApiAuthentication | None = None,
) -> ExecutionEvidence:
    if not cases:
        raise ValueError("no API cases to execute")
    if profile.environment == "analysis-only" or not profile.base_url_env:
        raise PermissionError("API execution requires an explicit test environment")
    runtime_env = env or os.environ
    base_url = runtime_env.get(profile.base_url_env, "").strip()
    if not base_url:
        raise ValueError(f"base URL environment variable is not set: {profile.base_url_env}")
    if request_func is None:
        import requests

        request_func = requests.request
    authentication_header, authentication_secrets = _authenticate(
        authentication,
        base_url=base_url,
        profile=profile,
        env=runtime_env,
        request_func=request_func,
    )
    started_at = datetime.now(tz=UTC)
    results = [
        _execute_case(
            case,
            base_url=base_url,
            profile=profile,
            env=runtime_env,
            request_func=request_func,
            authentication_header=authentication_header,
            authentication_secrets=authentication_secrets,
        )
        for case in cases
    ]
    counts = {
        status: sum(item.status == status for item in results)
        for status in ("passed", "failed", "error", "blocked")
    }
    return ExecutionEvidence(
        schema_version=EXECUTION_EVIDENCE_SCHEMA_VERSION,
        run_id=run_id,
        source_cases_path=source_cases_path,
        source_cases_schema_version=API_CASES_SCHEMA_VERSION,
        started_at=started_at,
        completed_at=datetime.now(tz=UTC),
        environment=ExecutionEnvironment(
            name=profile.environment,
            base_url_env=profile.base_url_env,
            base_url_configured=True,
            allowed_methods=profile.allowed_http_methods,
            request_timeout_seconds=profile.request_timeout_seconds,
        ),
        summary=ExecutionSummary(
            total=len(results),
            executed=counts["passed"] + counts["failed"] + counts["error"],
            passed=counts["passed"],
            failed=counts["failed"],
            errors=counts["error"],
            blocked=counts["blocked"],
        ),
        cases=results,
    )
