from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from harness.domain.models import (
    ApiAuthentication,
    ApiIsolationPolicy,
    ApiOperationPolicy,
    ApiTokenInjection,
    ExecutionProfile,
    LoginApiAuthentication,
    StaticTokenApiAuthentication,
    resolve_api_operation_policy,
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
    CorrelationContext,
    CorrelationDiagnostic,
    CorrelationObservation,
    ExecutionEnvironment,
    ExecutionEvidence,
    ExecutionSummary,
)
from harness.domain.security import (
    HTTP_HEADER_NAME,
    SECRET_KEY,
    build_api_request_url,
    validate_api_base_url,
    validate_api_base_url_policy,
    validate_api_request_transport,
    validate_api_response_url,
)
from harness.infrastructure.api_login_crypto import encrypt_login_request_body
from harness.infrastructure.api_runtime_policy import (
    apply_runtime_request_policies,
    derive_execution_namespace,
    derive_idempotency_key,
    validate_request_policy_compatibility,
)

ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)}")
FULL_VARIABLE_PLACEHOLDER_RE = re.compile(r"^\$\{\{([A-Za-z_][A-Za-z0-9_]*)}}$")
URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-fA-F]{2})-(?P<trace>[0-9a-fA-F]{32})-"
    r"(?P<span>[0-9a-fA-F]{16})-(?P<flags>[0-9a-fA-F]{2})$"
)
UTC = timezone.utc
ApiExecutionEventCallback = Callable[[str, dict[str, Any]], None]
_CURRENT_EVENT_CALLBACK: ContextVar[ApiExecutionEventCallback | None] = ContextVar(
    "api_execution_event_callback",
    default=None,
)
_CURRENT_CLEANUP_JOURNAL: ContextVar[Any | None] = ContextVar(
    "api_cleanup_journal",
    default=None,
)


class _MissingRuntimeVariable(RuntimeError):
    pass


class ApiAuthenticationError(RuntimeError):
    pass


def extract_correlation_context(
    headers: Mapping[str, Any],
    *,
    custom_headers: tuple[str, ...] = (),
) -> CorrelationContext:
    """Extract bounded correlation identifiers without persisting header values broadly."""
    values: dict[str, str] = {}
    diagnostics: list[CorrelationDiagnostic] = []
    builtin_headers = {
        "traceparent",
        "x-trace-id",
        "x-request-id",
        "request-id",
        "x-correlation-id",
        "x-tid",
        "tid",
    }
    allowed_custom = {
        name.casefold()
        for name in custom_headers
        if HTTP_HEADER_NAME.fullmatch(name) and not SECRET_KEY.search(name)
    }
    allowed_headers = builtin_headers | allowed_custom
    for raw_name, raw_value in headers.items():
        name = str(raw_name).casefold()
        if name not in allowed_headers:
            continue
        if not isinstance(raw_value, str) or not raw_value.strip():
            continue
        value = raw_value.strip()
        if len(value) > 256 or "\r" in value or "\n" in value:
            diagnostics.append(
                CorrelationDiagnostic(code="invalid_correlation_value", header_name=name)
            )
            continue
        previous = values.get(name)
        if previous is not None and previous != value:
            diagnostics.append(
                CorrelationDiagnostic(code="conflicting_header_value", header_name=name)
            )
            continue
        values[name] = value

    trace_id: str | None = None
    span_id: str | None = None
    trace_flags: str | None = None
    trace_source: str | None = None
    request_id: str | None = None
    custom_ids: dict[str, str] = {}
    observations: list[CorrelationObservation] = []
    traceparent = values.get("traceparent")
    if traceparent:
        match = TRACEPARENT_RE.fullmatch(traceparent)
        valid = bool(match)
        if match:
            version = match.group("version").casefold()
            trace = match.group("trace").casefold()
            span = match.group("span").casefold()
            valid = version != "ff" and trace != "0" * 32 and span != "0" * 16
        if valid and match:
            trace_id = trace
            span_id = span
            trace_flags = match.group("flags").casefold()
            trace_source = "traceparent"
            observations.extend(
                [
                    CorrelationObservation(field="trace_id", header_name="traceparent"),
                    CorrelationObservation(field="span_id", header_name="traceparent"),
                ]
            )
        else:
            diagnostics.append(
                CorrelationDiagnostic(code="malformed_traceparent", header_name="traceparent")
            )
    if trace_id is None and values.get("x-trace-id"):
        trace_id = values["x-trace-id"]
        trace_source = "response_header"
        observations.append(CorrelationObservation(field="trace_id", header_name="x-trace-id"))
    for name in ("x-request-id", "request-id"):
        if values.get(name):
            request_id = values[name]
            observations.append(CorrelationObservation(field="request_id", header_name=name))
            break
    for name in ("x-correlation-id", "x-tid", "tid", *sorted(allowed_custom)):
        if values.get(name) and name not in custom_ids:
            custom_ids[name] = values[name]
            observations.append(CorrelationObservation(field="custom_id", header_name=name))
    return CorrelationContext(
        trace_id=trace_id,
        span_id=span_id,
        trace_flags=trace_flags,
        trace_source=trace_source,
        request_id=request_id,
        custom_ids=custom_ids,
        observations=observations,
        diagnostics=diagnostics,
    )


@dataclass(frozen=True)
class _RequestOutcome:
    evidence: CaseExecutionEvidence
    extracted: dict[str, Any]
    request_sent: bool


def _emit_event(
    callback: ApiExecutionEventCallback | None,
    event_type: str,
    **payload: Any,
) -> None:
    callback = callback or _CURRENT_EVENT_CALLBACK.get()
    if callback is not None:
        callback(event_type, payload)


@contextmanager
def api_execution_events(callback: ApiExecutionEventCallback):
    token = _CURRENT_EVENT_CALLBACK.set(callback)
    try:
        yield
    finally:
        _CURRENT_EVENT_CALLBACK.reset(token)


@contextmanager
def api_cleanup_journal(journal: Any):
    token = _CURRENT_CLEANUP_JOURNAL.set(journal)
    try:
        yield
    finally:
        _CURRENT_CLEANUP_JOURNAL.reset(token)


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
    if value is None:
        return ["None", "null"]
    if isinstance(value, bool):
        return [str(value), json.dumps(value)]
    if isinstance(value, int | float):
        return [str(value)]
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
    return _json_strict_equal(actual, expected)


def _json_strict_equal(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _json_strict_equal(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _json_strict_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected, strict=True)
        )
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
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            if len(secret) <= 2:
                message = re.sub(
                    rf"(?<![A-Za-z0-9_]){re.escape(secret)}(?![A-Za-z0-9_])",
                    "<redacted>",
                    message,
                )
            else:
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
            raise RuntimeError("API authentication token is empty in the selected local project")
        return _injected_header(auth.injection, token), [token]
    if not isinstance(auth, LoginApiAuthentication):
        raise TypeError(f"unsupported API authentication configuration: {type(auth).__name__}")
    if auth.request.method not in profile.allowed_http_methods:
        raise PermissionError(
            f"API login method {auth.request.method} is not allowed by execution profile"
        )
    request = _resolve_required(auth.request.model_dump(mode="python"), env)
    try:
        request["body"] = encrypt_login_request_body(
            request.get("body"),
            auth.request_encryption,
            env,
        )
        request_url = build_api_request_url(base_url, auth.request.path)
        response = request_func(
            auth.request.method,
            request_url,
            headers=dict(request.get("headers") or {}),
            params=request.get("query"),
            json=request.get("body"),
            timeout=profile.request_timeout_seconds,
            allow_redirects=False,
        )
        validate_api_response_url(getattr(response, "url", None), requested_url=request_url)
        if int(response.status_code) not in set(auth.expected_status_codes):
            raise RuntimeError(f"API login returned HTTP {int(response.status_code)}")
        body = response.json()
        if auth.success_condition is not None:
            actual = _json_path_value(body, auth.success_condition.json_path)
            expected = auth.success_condition.expected
            if type(actual) is not type(expected) or actual != expected:
                raise RuntimeError("API login business success condition was not met")
        token = _json_path_value(body, auth.token_json_path)
        if not isinstance(token, str) or not token.strip():
            raise RuntimeError("API login response token must be a non-empty string")
        token = token.strip()
        return _injected_header(auth.injection, token), [token]
    except Exception as exc:
        message = _sanitize_error(exc, [base_url, *env.values()])
        raise ApiAuthenticationError(f"API authentication failed: {message}") from exc


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
) -> tuple[list[AssertionEvidence], Any | None, bool, list[str]]:
    evidence: list[AssertionEvidence] = []
    errors: list[str] = []
    body: Any | None = None
    body_loaded = False
    for assertion in assertions:
        try:
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
                    _json_strict_equal(actual, assertion.expected)
                    if assertion.type == "json_field_equals"
                    else _json_contains(actual, assertion.expected)
                )
                evidence.append(
                    AssertionEvidence(
                        type=assertion.type,
                        passed=passed,
                        expected=_value_summary(assertion.expected, present=True),
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
                        expected=_value_summary(assertion.expected, present=True),
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
        except Exception as exc:
            error = f"{assertion.type} evaluation raised {type(exc).__name__}"
            errors.append(error)
            evidence.append(
                AssertionEvidence(
                    type=assertion.type,
                    passed=False,
                    path=assertion.path,
                    message=error,
                )
            )
    return evidence, body, body_loaded, errors


def _extract_response_variables(
    definitions: Mapping[str, ApiVariableExtraction],
    response: Any,
    *,
    body: Any | None,
    body_loaded: bool,
) -> tuple[dict[str, Any], list[str]]:
    extracted: dict[str, Any] = {}
    missing_required: list[str] = []
    for name, definition in definitions.items():
        try:
            if definition.source == "response_json":
                if not body_loaded:
                    body = response.json()
                    body_loaded = True
                found, value = _json_path_lookup(body, definition.path)
            else:
                found, value = _response_header(response, definition.path)
        except Exception:
            found, value = False, None
        if not found:
            if definition.required:
                missing_required.append(name)
            continue
        extracted[name] = value
    return extracted, missing_required


def _execute_request(
    *,
    case_id: str,
    dataset_id: str | None,
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
    execution_id: str = "",
    isolation: ApiIsolationPolicy | None = None,
    operation_policy: ApiOperationPolicy | None = None,
    namespace_value: str | None = None,
    cleanup_steps: list[ApiCleanupStep] | None = None,
    definition_error: str | None = None,
    event_callback: ApiExecutionEventCallback | None = None,
    correlation_response_headers: tuple[str, ...] = (),
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
                dataset_id=dataset_id,
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
                dataset_id=dataset_id,
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
                dataset_id=dataset_id,
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
    isolation = isolation or ApiIsolationPolicy()
    operation_policy = operation_policy or resolve_api_operation_policy({}, method, path)
    if operation_policy.classification == "mutation_manual":
        return _RequestOutcome(
            evidence=CaseExecutionEvidence(
                case_id=case_id,
                dataset_id=dataset_id,
                title=title,
                method=method,
                path=path,
                status="blocked",
                started_at=started_at,
                completed_at=datetime.now(tz=UTC),
                duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
                error="API operation is manual-only in the reviewed execution policy",
            ),
            extracted={},
            request_sent=False,
        )
    idempotency_key = (
        derive_idempotency_key(
            execution_id,
            case_id,
            method,
            path,
            prefix=operation_policy.idempotency_key_prefix,
        )
        if operation_policy.classification == "mutation_idempotent"
        else None
    )
    redactions = [
        base_url,
        *env.values(),
        *authentication_secrets,
        *_runtime_redactions(runtime_redaction_values or {}),
        *(value for value in (namespace_value, idempotency_key) if value),
    ]
    try:
        _emit_event(
            event_callback,
            "request.preparing",
            case_id=case_id,
            method=method,
            path=path,
        )
        request = _resolve_runtime_variables(
            request_definition.model_dump(mode="python"), runtime_variables
        )
        missing_environment = sorted(
            name for name in _required_environment_references(request) if not env.get(name)
        )
        if missing_environment:
            raise _MissingRuntimeVariable(
                "API request is missing environment values: " + ", ".join(missing_environment)
            )
        request = _resolve(request, env)
        request = apply_runtime_request_policies(
            request,
            isolation=isolation,
            namespace_value=namespace_value,
            operation_policy=operation_policy,
            idempotency_key=idempotency_key,
        )
        resolved_path = str(request.get("path") or "")
        try:
            validate_api_request_transport(
                path=resolved_path,
                headers=dict(request.get("headers") or {}),
                label="resolved API request",
            )
        except ValueError as exc:
            raise _MissingRuntimeVariable(str(exc)) from exc
        headers = _apply_authentication_header(
            dict(request.get("headers") or {}),
            authentication_header,
        )
        request_url = build_api_request_url(base_url, resolved_path)
        if namespace_value is not None:
            _emit_event(
                event_callback,
                "isolation.applied",
                case_id=case_id,
                mode=isolation.mode,
                location=isolation.namespace.location if isolation.namespace else None,
                name=isolation.namespace.name if isolation.namespace else None,
                value_sha256=hashlib.sha256(namespace_value.encode()).hexdigest(),
            )
        if idempotency_key is not None:
            _emit_event(
                event_callback,
                "idempotency.configured",
                case_id=case_id,
                header=operation_policy.idempotency_header,
                key_sha256=hashlib.sha256(idempotency_key.encode()).hexdigest(),
            )
        journal = _CURRENT_CLEANUP_JOURNAL.get()
        if operation_policy.classification != "read_only":
            _emit_event(
                event_callback,
                "mutation.intent.created",
                case_id=case_id,
                method=method,
                path=path,
                operation_classification=operation_policy.classification,
            )
        if journal is not None:
            for cleanup in cleanup_steps or []:
                journal.arm(
                    case_id=case_id,
                    title=title,
                    cleanup=cleanup,
                    runtime_variables=dict(runtime_variables),
                    request_operation=f"{method} {path}",
                    request_idempotency_key=idempotency_key,
                )
                _emit_event(
                    event_callback,
                    "cleanup.armed",
                    case_id=case_id,
                    cleanup_id=cleanup.id,
                    request_operation=f"{method} {path}",
                )
        _emit_event(
            event_callback,
            "request.sent",
            case_id=case_id,
            method=method,
            path=path,
        )
        request_sent = True
        response = request_func(
            method,
            request_url,
            headers=headers,
            params=request.get("query"),
            json=request.get("body"),
            timeout=profile.request_timeout_seconds,
            allow_redirects=False,
        )
        validate_api_response_url(getattr(response, "url", None), requested_url=request_url)
        correlation = extract_correlation_context(
            getattr(response, "headers", {}) or {},
            custom_headers=correlation_response_headers,
        )
        response_duration_ms = max(0, int((perf_counter() - started_clock) * 1000))
        _emit_event(
            event_callback,
            "response.received",
            case_id=case_id,
            method=method,
            path=path,
            status_code=int(response.status_code),
            duration_ms=response_duration_ms,
        )
        evidence, body, body_loaded, assertion_errors = _evaluate_assertions(
            assertions,
            response,
            response_duration_ms=response_duration_ms,
        )
        extracted, missing_required = _extract_response_variables(
            extractions,
            response,
            body=body,
            body_loaded=body_loaded,
        )
        for assertion in evidence:
            _emit_event(
                event_callback,
                "assertion.finished",
                case_id=case_id,
                assertion_type=assertion.type,
                passed=assertion.passed,
                path=assertion.path,
            )
        if extractions:
            _emit_event(
                event_callback,
                "extraction.finished",
                case_id=case_id,
                extracted_names=sorted(extracted),
                missing_required=sorted(missing_required),
            )
        if missing_required:
            return _RequestOutcome(
                evidence=CaseExecutionEvidence(
                    case_id=case_id,
                    dataset_id=dataset_id,
                    title=title,
                    method=method,
                    path=path,
                    status="error",
                    started_at=started_at,
                    completed_at=datetime.now(tz=UTC),
                    duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
                    status_code=int(response.status_code),
                    assertions=evidence,
                    error=(
                        "required response variable extraction failed: "
                        + ", ".join(missing_required)
                    ),
                    request_dispatched=True,
                    correlation=correlation,
                ),
                extracted=extracted,
                request_sent=True,
            )
        if assertion_errors:
            return _RequestOutcome(
                evidence=CaseExecutionEvidence(
                    case_id=case_id,
                    dataset_id=dataset_id,
                    title=title,
                    method=method,
                    path=path,
                    status="error",
                    started_at=started_at,
                    completed_at=datetime.now(tz=UTC),
                    duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
                    status_code=int(response.status_code),
                    assertions=evidence,
                    error="; ".join(assertion_errors),
                    request_dispatched=True,
                    correlation=correlation,
                ),
                extracted=extracted,
                request_sent=True,
            )
        status = "passed" if evidence and all(item.passed for item in evidence) else "failed"
        return _RequestOutcome(
            evidence=CaseExecutionEvidence(
                case_id=case_id,
                dataset_id=dataset_id,
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
                request_dispatched=True,
                correlation=correlation,
            ),
            extracted=extracted,
            request_sent=True,
        )
    except _MissingRuntimeVariable as exc:
        return _RequestOutcome(
            evidence=CaseExecutionEvidence(
                case_id=case_id,
                dataset_id=dataset_id,
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
        if request_sent:
            _emit_event(
                event_callback,
                "request.indeterminate",
                case_id=case_id,
                method=method,
                path=path,
                error_kind=type(exc).__name__,
            )
        return _RequestOutcome(
            evidence=CaseExecutionEvidence(
                case_id=case_id,
                dataset_id=dataset_id,
                title=title,
                method=method,
                path=path,
                status="error",
                started_at=started_at,
                completed_at=datetime.now(tz=UTC),
                duration_ms=max(0, int((perf_counter() - started_clock) * 1000)),
                error=_sanitize_error(exc, redactions),
                request_dispatched=request_sent,
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
    trusted_origins: list[str] | None = None,
    isolation: ApiIsolationPolicy | None = None,
    operation_policies: dict[str, ApiOperationPolicy] | None = None,
    execution_identity: str | None = None,
    event_callback: ApiExecutionEventCallback | None = None,
    source_cases_schema_version: str = API_CASES_SCHEMA_VERSION,
    correlation_response_headers: tuple[str, ...] = (),
) -> ExecutionEvidence:
    isolation = isolation or ApiIsolationPolicy()
    operation_policies = operation_policies or {}
    execution_identity = execution_identity or run_id
    namespace_value = (
        derive_execution_namespace(execution_identity, prefix=isolation.namespace.prefix)
        if isolation.mode == "namespace" and isolation.namespace is not None
        else None
    )
    started_at = datetime.now(tz=UTC)
    runtime_env, base_url, definition_errors = _prepare_api_execution(
        cases,
        profile=profile,
        env=env,
        authentication=authentication,
        trusted_origins=trusted_origins,
    )
    if request_func is None:
        import requests

        request_func = requests.request
    has_executable_case = any(
        definition_errors[index] is None
        and case.contract_status == "confirmed"
        and bool(case.request.method)
        and bool(case.request.path)
        and str(case.request.method).upper() in profile.allowed_http_methods
        for index, case in enumerate(cases)
    )
    if has_executable_case:
        _emit_event(event_callback, "authentication.started")
        try:
            authentication_header, authentication_secrets = _authenticate(
                authentication,
                base_url=base_url,
                profile=profile,
                env=runtime_env,
                request_func=request_func,
            )
        except Exception as exc:
            _emit_event(
                event_callback,
                "authentication.failed",
                error_kind=type(exc).__name__,
            )
            raise
        _emit_event(
            event_callback,
            "authentication.finished",
            configured=authentication is not None,
        )
    else:
        authentication_header, authentication_secrets = None, []
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
                dataset_id=None,
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
                execution_id=execution_identity,
                isolation=isolation,
                operation_policy=resolve_api_operation_policy(
                    operation_policies, case.request.method, case.request.path
                ),
                namespace_value=namespace_value,
                definition_error=definition_error,
                event_callback=event_callback,
                correlation_response_headers=correlation_response_headers,
            )
            results.append(outcome.evidence)
            _emit_event(
                event_callback,
                "case.finished",
                case_id=outcome.evidence.case_id,
                status=outcome.evidence.status,
                duration_ms=outcome.evidence.duration_ms,
                status_code=outcome.evidence.status_code,
            )
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
                dataset_id=None if dataset is None else dataset.id,
                title=title,
                request_definition=case.request,
                assertions=case.assertions,
                extractions=variable_definition.extract,
                contract_confirmed=case.contract_status == "confirmed",
                base_url=base_url,
                profile=profile,
                env=runtime_env,
                runtime_variables=runtime_variables,
                runtime_redaction_values=runtime_variables,
                request_func=request_func,
                authentication_header=authentication_header,
                authentication_secrets=authentication_secrets,
                execution_id=execution_identity,
                isolation=isolation,
                operation_policy=resolve_api_operation_policy(
                    operation_policies, case.request.method, case.request.path
                ),
                namespace_value=namespace_value,
                cleanup_steps=cleanup_steps,
                event_callback=event_callback,
                correlation_response_headers=correlation_response_headers,
            )
            results.append(outcome.evidence)
            _emit_event(
                event_callback,
                "case.finished",
                case_id=outcome.evidence.case_id,
                status=outcome.evidence.status,
                duration_ms=outcome.evidence.duration_ms,
                status_code=outcome.evidence.status_code,
            )
            if outcome.evidence.status == "passed" and outcome.extracted:
                shared_variables.update(outcome.extracted)
            if outcome.request_sent:
                cleanup_scope = {**runtime_variables, **outcome.extracted}
                cleanup_redactions = cleanup_scope
                for step in cleanup_steps:
                    journal = _CURRENT_CLEANUP_JOURNAL.get()
                    ready = _cleanup_request_is_resolvable(step, cleanup_scope)
                    if journal is not None:
                        obligation_id = f"{case_id}::cleanup::{step.id}"
                        journal.enrich(
                            obligation_id,
                            runtime_variables=cleanup_scope,
                            ready=ready,
                        )
                    if not ready and journal is not None:
                        _emit_event(
                            event_callback,
                            "cleanup.indeterminate",
                            case_id=case_id,
                            cleanup_id=step.id,
                            status="blocked",
                            missing_runtime_variables=True,
                        )
                        continue
                    _emit_event(
                        event_callback,
                        "cleanup.registered",
                        case_id=case_id,
                        cleanup_id=step.id,
                    )
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
        obligation_id = f"{case_id}::cleanup::{step.id}"
        journal = _CURRENT_CLEANUP_JOURNAL.get()
        if journal is not None:
            journal.before(obligation_id)
        _emit_event(
            event_callback,
            "cleanup.started",
            case_id=case_id,
            cleanup_id=step.id,
        )
        outcome = _execute_request(
            case_id=f"{case_id}::cleanup::{step.id}",
            dataset_id=case_id.split("::", 1)[1] if "::" in case_id else None,
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
            execution_id=execution_identity,
            isolation=isolation,
            operation_policy=resolve_api_operation_policy(
                operation_policies, step.request.method, step.request.path
            ),
            namespace_value=namespace_value,
            event_callback=event_callback,
            correlation_response_headers=correlation_response_headers,
        )
        results.append(outcome.evidence)
        if journal is not None:
            journal.after(
                obligation_id,
                status=outcome.evidence.status,
                request_sent=outcome.request_sent,
            )
        _emit_event(
            event_callback,
            "cleanup.finished",
            case_id=case_id,
            cleanup_id=step.id,
            status=outcome.evidence.status,
            duration_ms=outcome.evidence.duration_ms,
            status_code=outcome.evidence.status_code,
        )
    counts = {
        status: sum(item.status == status for item in results)
        for status in ("passed", "failed", "error", "blocked")
    }
    return ExecutionEvidence(
        schema_version=EXECUTION_EVIDENCE_SCHEMA_VERSION,
        run_id=run_id,
        source_cases_path=source_cases_path,
        source_cases_schema_version=source_cases_schema_version,
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


def _cleanup_request_is_resolvable(
    cleanup: ApiCleanupStep,
    runtime_variables: Mapping[str, Any],
) -> bool:
    try:
        _resolve_runtime_variables(
            cleanup.request.model_dump(mode="python"),
            runtime_variables,
        )
    except _MissingRuntimeVariable:
        return False
    return True


def validate_api_execution_preflight(
    cases: list[ApiTestCase],
    *,
    profile: ExecutionProfile,
    env: Mapping[str, str] | None = None,
    authentication: ApiAuthentication | None = None,
    trusted_origins: list[str] | None = None,
    isolation: ApiIsolationPolicy | None = None,
    operation_policies: dict[str, ApiOperationPolicy] | None = None,
) -> None:
    _runtime_env, _base_url, definition_errors = _prepare_api_execution(
        cases,
        profile=profile,
        env=env,
        authentication=authentication,
        trusted_origins=trusted_origins,
    )
    isolation = isolation or ApiIsolationPolicy()
    operation_policies = operation_policies or {}
    for index, case in enumerate(cases):
        if definition_errors[index] is not None or case.contract_status != "confirmed":
            continue
        policy = resolve_api_operation_policy(
            operation_policies, case.request.method, case.request.path
        )
        operation = f"{case.request.method} {case.request.path}"
        if policy.classification == "mutation_manual":
            raise PermissionError(f"manual-only API operation cannot execute: {operation}")
        validate_request_policy_compatibility(
            case.request.model_dump(mode="python"),
            isolation=isolation,
            operation_policy=policy,
        )
        for step in parse_api_cleanup_steps(case.cleanup):
            validate_request_policy_compatibility(
                step.request.model_dump(mode="python"),
                isolation=isolation,
                operation_policy=resolve_api_operation_policy(
                    operation_policies, step.request.method, step.request.path
                ),
            )


def _prepare_api_execution(
    cases: list[ApiTestCase],
    *,
    profile: ExecutionProfile,
    env: Mapping[str, str] | None,
    authentication: ApiAuthentication | None,
    trusted_origins: list[str] | None,
) -> tuple[Mapping[str, str], str, list[str | None]]:
    if not cases:
        raise ValueError("no API cases to execute")
    if profile.environment == "analysis-only" or not profile.base_url_env:
        raise PermissionError("API execution requires an explicit test environment")
    runtime_env = {} if env is None else env
    base_url = runtime_env.get(profile.base_url_env, "").strip()
    if not base_url:
        raise ValueError("API base URL is empty in the selected local project")
    base_url = (
        validate_api_base_url_policy(base_url, trusted_origins=trusted_origins)
        if trusted_origins is not None
        else validate_api_base_url(base_url)
    )
    definition_errors = api_case_runtime_definition_errors(cases)
    for index, case in enumerate(cases):
        if definition_errors[index] is not None:
            continue
        variables = parse_api_case_variables(case.variables)
        cleanup = parse_api_cleanup_steps(case.cleanup)
        environment_payloads = [
            case.request.model_dump(mode="python"),
            *(dataset.values for dataset in variables.datasets),
            *(step.request.model_dump(mode="python") for step in cleanup),
        ]
        missing_environment = sorted(
            {
                name
                for payload in environment_payloads
                for name in _required_environment_references(payload)
                if not runtime_env.get(name)
            }
        )
        if missing_environment:
            definition_errors[index] = "API case is missing environment values: " + ", ".join(
                missing_environment
            )
    has_executable_case = any(
        definition_errors[index] is None
        and case.contract_status == "confirmed"
        and bool(case.request.method)
        and bool(case.request.path)
        and str(case.request.method).upper() in profile.allowed_http_methods
        for index, case in enumerate(cases)
    )
    if has_executable_case and isinstance(authentication, StaticTokenApiAuthentication):
        token = (
            authentication.token.get_secret_value().strip()
            if authentication.token is not None
            else runtime_env.get(str(authentication.token_env), "").strip()
        )
        if not token:
            raise RuntimeError("API authentication token is empty in the selected local project")
    elif has_executable_case and isinstance(authentication, LoginApiAuthentication):
        if authentication.request.method not in profile.allowed_http_methods:
            raise PermissionError(
                f"API login method {authentication.request.method} is not allowed by "
                "execution profile"
            )
        login_request = _resolve_required(
            authentication.request.model_dump(mode="python"), runtime_env
        )
        encrypt_login_request_body(
            login_request.get("body"),
            authentication.request_encryption,
            runtime_env,
        )
        build_api_request_url(base_url, authentication.request.path)
    return runtime_env, base_url, definition_errors
