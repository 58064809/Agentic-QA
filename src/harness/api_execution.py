from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from harness.contracts import ExecutionProfile
from harness.schemas.api_test_cases import API_CASES_SCHEMA_VERSION, ApiTestCase
from harness.schemas.execution_evidence import (
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


def _json_path_exists(body: Any, path: str) -> bool:
    if not path.startswith("$."):
        return False
    current = body
    for part in path[2:].split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _sanitize_error(error: Exception, secrets: list[str]) -> str:
    message = URL_RE.sub("<redacted-url>", str(error))
    for secret in secrets:
        if secret:
            message = message.replace(secret, "<redacted>")
    return message[:1000]


def _execute_case(
    case: ApiTestCase,
    *,
    base_url: str,
    profile: ExecutionProfile,
    env: Mapping[str, str],
    request_func: Callable[..., Any],
) -> CaseExecutionEvidence:
    method = str(case.request.method or "GET").upper()
    path = str(case.request.path or "/")
    started_at = datetime.now(tz=UTC)
    started_clock = perf_counter()
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
        response = request_func(
            method,
            base_url.rstrip("/") + "/" + path.lstrip("/"),
            headers=dict(request.get("headers") or {}),
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
            error=_sanitize_error(exc, [base_url, *env.values()]),
        )


def execute_api_cases(
    cases: list[ApiTestCase],
    *,
    run_id: str,
    source_cases_path: str,
    profile: ExecutionProfile,
    env: Mapping[str, str] | None = None,
    request_func: Callable[..., Any] | None = None,
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
    started_at = datetime.now(tz=UTC)
    results = [
        _execute_case(
            case,
            base_url=base_url,
            profile=profile,
            env=runtime_env,
            request_func=request_func,
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
