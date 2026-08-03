from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
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
from harness.domain.schemas.api_test_cases import (
    API_CASES_SCHEMA_VERSION,
    VARIABLE_PLACEHOLDER,
    ApiAssertion,
    ApiCleanupStep,
    ApiRequest,
    ApiTestCase,
    ApiVariableExtraction,
    api_case_runtime_definition_errors,
    json_path_tokens,
    parse_api_case_variables,
    parse_api_cleanup_steps,
)
from harness.domain.schemas.execution_evidence import (
    EXECUTION_EVIDENCE_SCHEMA_VERSION,
    AssertionEvidence,
    CaseExecutionEvidence,
    ExecutionEnvironment,
    ExecutionEvidence,
    ExecutionSummary,
)

ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)}")
FULL_VARIABLE_PLACEHOLDER_RE = re.compile(r"^\$\{\{([A-Za-z_][A-Za-z0-9_]*)}}$")
URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
UTC = timezone.utc


class _MissingRuntimeVariable(RuntimeError):
    pass


@dataclass(frozen=True)
class _RequestOutcome:
    evidence: CaseExecutionEvidence
    extracted: dict[str, Any]
    request_sent: bool


def _resolve(value: Any, env: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return ENV_PLACEHOLDER_RE.sub(lambda match: env.get(match.group(1), ""), value)
    if isinstance(value, list):
        return [_resolve(item, env) for item in value]
    if isinstance(value, dict):
        return {key: _resolve(item, env) for key, item in value.items()}
    return value


def _resolve_runtime_variables(value: Any, variables: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        exact = FULL_VARIABLE_PLACEHOLDER_RE.fullmatch(value)
        if exact:
            name = exact.group(1)
            if name not in variables:
                raise _MissingRuntimeVariable(f"runtime variable is unavailable: {name}")
            return variables[name]

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in variables:
                raise _MissingRuntimeVariable(f"runtime variable is unavailable: {name}")
            item = variables[name]
            if item is None or isinstance(item, dict | list):
                raise _MissingRuntimeVariable(
                    f"runtime variable must be scalar when embedded in text: {name}"
                )
            return str(item)

        return VARIABLE_PLACEHOLDER.sub(replace, value)
    if isinstance(value, list):
        return [_resolve_runtime_variables(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_runtime_variables(item, variables) for key, item in value.items()}
    return value


def _runtime_redactions(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [item for value_item in value for item in _runtime_redactions(value_item)]
    if isinstance(value, dict):
        return [item for value_item in value.values() for item in _runtime_redactions(value_item)]
    return []


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


def _json_path_lookup(body: Any, path: str) -> tuple[bool, Any]:
    try:
        tokens = json_path_tokens(path)
    except ValueError:
        return False, None
    current = body
    for token in tokens:
        if isinstance(token, str):
            if not isinstance(current, dict) or token not in current:
                return False, None
            current = current[token]
        else:
            if not isinstance(current, list) or token >= len(current):
                return False, None
            current = current[token]
    return True, current


def _json_contains(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _json_contains(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(_json_contains(candidate, item) for candidate in actual) for item in expected
        )
    if isinstance(expected, str):
        return isinstance(actual, str) and expected in actual
    return actual == expected


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _value_summary(value: Any, *, present: bool = True) -> dict[str, Any]:
    if not present:
        return {"present": False}
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda _value: "<non-json-value>",
    ).encode("utf-8")
    return {
        "present": True,
        "type": _json_type(value),
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }


def _response_header(response: Any, name: str) -> tuple[bool, str | None]:
    headers = getattr(response, "headers", {})
    if not isinstance(headers, Mapping):
        return False, None
    for key, value in headers.items():
        if str(key).casefold() == name.casefold():
            return True, str(value)
    return False, None


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


def _evaluate_assertions(
    assertions: list[ApiAssertion],
    response: Any,
    *,
    response_duration_ms: int,
) -> tuple[list[AssertionEvidence], Any | None, bool]:
    evidence: list[AssertionEvidence] = []
    body: Any | None = None
    body_loaded = False
    for assertion in assertions:
        if assertion.type == "status_code":
            expected = assertion.expected
            codes = (
                {int(item) for item in expected} if isinstance(expected, list) else {int(expected)}
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
            if not body_loaded:
                body = response.json()
                body_loaded = True
            found, _actual = _json_path_lookup(body, assertion.path or "")
            evidence.append(
                AssertionEvidence(
                    type=assertion.type,
                    passed=found,
                    expected=True,
                    actual=found,
                    path=assertion.path,
                )
            )
        elif assertion.type in {"json_field_equals", "json_field_contains"}:
            if not body_loaded:
                body = response.json()
                body_loaded = True
            found, actual = _json_path_lookup(body, assertion.path or "")
            passed = found and (
                actual == assertion.expected
                if assertion.type == "json_field_equals"
                else _json_contains(actual, assertion.expected)
            )
            evidence.append(
                AssertionEvidence(
                    type=assertion.type,
                    passed=passed,
                    expected=assertion.expected,
                    actual=_value_summary(actual, present=found),
                    path=assertion.path,
                    message="raw response value omitted",
                )
            )
        elif assertion.type == "header_equals":
            found, actual_header = _response_header(response, assertion.path or "")
            evidence.append(
                AssertionEvidence(
                    type=assertion.type,
                    passed=found and actual_header == assertion.expected,
                    expected=assertion.expected,
                    actual=_value_summary(actual_header, present=found),
                    path=assertion.path,
                    message="raw response header value omitted",
                )
            )
        elif assertion.type == "response_time_ms_max":
            maximum = int(assertion.expected)
            evidence.append(
                AssertionEvidence(
                    type=assertion.type,
                    passed=response_duration_ms <= maximum,
                    expected=maximum,
                    actual=response_duration_ms,
                )
            )
    return evidence, body, body_loaded


def _extract_response_variables(
    definitions: Mapping[str, ApiVariableExtraction],
    response: Any,
    *,
    body: Any | None,
    body_loaded: bool,
) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    for name, definition in definitions.items():
        if definition.source == "response_json":
            if not body_loaded:
                body = response.json()
                body_loaded = True
            found, value = _json_path_lookup(body, definition.path)
        else:
            found, value = _response_header(response, definition.path)
        if not found:
            if definition.required:
                raise RuntimeError(f"required response variable extraction failed: {name}")
            continue
        extracted[name] = value
    return extracted


def _execute_request(
    *,
    case_id: str,
    title: str,
    request_definition: ApiRequest,
    assertions: list[ApiAssertion],
    extractions: Mapping[str, ApiVariableExtraction],
    contract_confirmed: bool,
    base_url: str,
    profile: ExecutionProfile,
    env: Mapping[str, str],
    runtime_variables: Mapping[str, Any],
    runtime_redaction_values: Mapping[str, Any] | None,
    request_func: Callable[..., Any],
    authentication_header: tuple[str, str] | None,
    authentication_secrets: list[str],
    definition_error: str | None = None,
) -> _RequestOutcome:
    method = str(request_definition.method or "").upper()
    path = str(request_definition.path or "")
    started_at = datetime.now(tz=UTC)
    started_clock = perf_counter()
    if definition_error is not None:
        definition_category = (
            "API assertion definition is invalid"
            if definition_error.startswith("assertions[")
            else "API runtime definition is invalid"
        )
        return _RequestOutcome(
            evidence=CaseExecutionEvidence(
                case_id=case_id,
                title=title,
                method=method,
                path=path,
                status="blocked",
                started_at=started_at,
                completed_at=datetime.now(tz=UTC),
                duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
                error=f"{definition_category}: {definition_error}",
            ),
            extracted={},
            request_sent=False,
        )
    if not contract_confirmed or not method or not path:
        return _RequestOutcome(
            evidence=CaseExecutionEvidence(
                case_id=case_id,
                title=title,
                method=method,
                path=path,
                status="blocked",
                started_at=started_at,
                completed_at=datetime.now(tz=UTC),
                duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
                error="API contract is not confirmed",
            ),
            extracted={},
            request_sent=False,
        )
    if path.startswith(("http://", "https://")):
        raise ValueError("API case path must be relative")
    if method not in profile.allowed_http_methods:
        return _RequestOutcome(
            evidence=CaseExecutionEvidence(
                case_id=case_id,
                title=title,
                method=method,
                path=path,
                status="blocked",
                started_at=started_at,
                completed_at=datetime.now(tz=UTC),
                duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
                error=f"HTTP method {method} is not allowed by execution profile",
            ),
            extracted={},
            request_sent=False,
        )
    request_sent = False
    redactions = [
        base_url,
        *env.values(),
        *authentication_secrets,
        *_runtime_redactions(runtime_redaction_values or {}),
    ]
    try:
        request = _resolve_runtime_variables(
            request_definition.model_dump(mode="python"), runtime_variables
        )
        request = _resolve(request, env)
        resolved_path = str(request.get("path") or "")
        if not resolved_path.startswith("/") or resolved_path.startswith("//"):
            raise ValueError("resolved API case path must be relative and start with '/'")
        headers = _apply_authentication_header(
            dict(request.get("headers") or {}),
            authentication_header,
        )
        request_sent = True
        response = request_func(
            method,
            base_url.rstrip("/") + "/" + resolved_path.lstrip("/"),
            headers=headers,
            params=request.get("query"),
            json=request.get("body"),
            timeout=profile.request_timeout_seconds,
        )
        response_duration_ms = max(0, int((perf_counter() - started_clock) * 1000))
        evidence, body, body_loaded = _evaluate_assertions(
            assertions,
            response,
            response_duration_ms=response_duration_ms,
        )
        extracted = _extract_response_variables(
            extractions,
            response,
            body=body,
            body_loaded=body_loaded,
        )
        status = "passed" if evidence and all(item.passed for item in evidence) else "failed"
        return _RequestOutcome(
            evidence=CaseExecutionEvidence(
                case_id=case_id,
                title=title,
                method=method,
                path=path,
                status=status,
                started_at=started_at,
                completed_at=datetime.now(tz=UTC),
                duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
                status_code=int(response.status_code),
                assertions=evidence,
                error=None if status == "passed" else "one or more assertions failed",
            ),
            extracted=extracted,
            request_sent=True,
        )
    except _MissingRuntimeVariable as exc:
        return _RequestOutcome(
            evidence=CaseExecutionEvidence(
                case_id=case_id,
                title=title,
                method=method,
                path=path,
                status="blocked",
                started_at=started_at,
                completed_at=datetime.now(tz=UTC),
                duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
                error=str(exc),
            ),
            extracted={},
            request_sent=False,
        )
    except Exception as exc:
        return _RequestOutcome(
            evidence=CaseExecutionEvidence(
                case_id=case_id,
                title=title,
                method=method,
                path=path,
                status="error",
                started_at=started_at,
                completed_at=datetime.now(tz=UTC),
                duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
                error=_sanitize_error(exc, redactions),
            ),
            extracted={},
            request_sent=request_sent,
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
    definition_errors = api_case_runtime_definition_errors(cases)
    has_executable_case = any(
        definition_errors[index] is None
        and case.contract_status == "confirmed"
        and bool(case.request.method)
        and bool(case.request.path)
        and str(case.request.method).upper() in profile.allowed_http_methods
        for index, case in enumerate(cases)
    )
    if has_executable_case:
        authentication_header, authentication_secrets = _authenticate(
            authentication,
            base_url=base_url,
            profile=profile,
            env=runtime_env,
            request_func=request_func,
        )
    else:
        authentication_header, authentication_secrets = None, []
    started_at = datetime.now(tz=UTC)
    results: list[CaseExecutionEvidence] = []
    shared_variables: dict[str, Any] = {}
    cleanup_queue: list[
        tuple[ApiTestCase, ApiCleanupStep, str, str, dict[str, Any], dict[str, Any]]
    ] = []
    for index, case in enumerate(cases):
        definition_error = definition_errors[index]
        if definition_error is not None:
            outcome = _execute_request(
                case_id=case.id,
                title=case.title,
                request_definition=case.request,
                assertions=case.assertions,
                extractions={},
                contract_confirmed=case.contract_status == "confirmed",
                base_url=base_url,
                profile=profile,
                env=runtime_env,
                runtime_variables=shared_variables,
                runtime_redaction_values=shared_variables,
                request_func=request_func,
                authentication_header=authentication_header,
                authentication_secrets=authentication_secrets,
                definition_error=definition_error,
            )
            results.append(outcome.evidence)
            continue

        variable_definition = parse_api_case_variables(case.variables)
        cleanup_steps = parse_api_cleanup_steps(case.cleanup)
        datasets = variable_definition.datasets or [None]
        for dataset in datasets:
            dataset_values = {} if dataset is None else dataset.values
            runtime_variables = {**shared_variables, **dataset_values}
            case_id = case.id if dataset is None else f"{case.id}::{dataset.id}"
            title = case.title if dataset is None else f"{case.title} [dataset:{dataset.id}]"
            outcome = _execute_request(
                case_id=case_id,
                title=title,
                request_definition=case.request,
                assertions=case.assertions,
                extractions=variable_definition.extract,
                contract_confirmed=case.contract_status == "confirmed",
                base_url=base_url,
                profile=profile,
                env=runtime_env,
                runtime_variables=runtime_variables,
                runtime_redaction_values=shared_variables,
                request_func=request_func,
                authentication_header=authentication_header,
                authentication_secrets=authentication_secrets,
            )
            results.append(outcome.evidence)
            if outcome.extracted:
                shared_variables.update(outcome.extracted)
            if outcome.request_sent:
                cleanup_scope = {**runtime_variables, **outcome.extracted}
                cleanup_redactions = {**shared_variables, **outcome.extracted}
                for step in cleanup_steps:
                    cleanup_queue.append(
                        (
                            case,
                            step,
                            case_id,
                            title,
                            cleanup_scope,
                            cleanup_redactions,
                        )
                    )

    for case, step, case_id, title, runtime_variables, redaction_values in reversed(cleanup_queue):
        outcome = _execute_request(
            case_id=f"{case_id}::cleanup::{step.id}",
            title=f"{title} / cleanup: {step.title}",
            request_definition=step.request,
            assertions=step.assertions,
            extractions={},
            contract_confirmed=case.contract_status == "confirmed",
            base_url=base_url,
            profile=profile,
            env=runtime_env,
            runtime_variables=runtime_variables,
            runtime_redaction_values=redaction_values,
            request_func=request_func,
            authentication_header=authentication_header,
            authentication_secrets=authentication_secrets,
        )
        results.append(outcome.evidence)
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
