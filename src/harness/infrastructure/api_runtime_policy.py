from __future__ import annotations

import hashlib
from typing import Any

from harness.domain.models import ApiIsolationPolicy, ApiOperationPolicy


def derive_execution_namespace(execution_id: str, *, prefix: str) -> str:
    digest = hashlib.sha256(execution_id.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def derive_idempotency_key(
    execution_id: str,
    case_id: str,
    method: str,
    path_template: str,
    *,
    prefix: str,
) -> str:
    identity = "\x00".join((execution_id, case_id, method, path_template))
    return f"{prefix}-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def validate_request_policy_compatibility(
    request: dict[str, Any],
    *,
    isolation: ApiIsolationPolicy,
    operation_policy: ApiOperationPolicy,
) -> None:
    headers = request.get("headers") or {}
    if not isinstance(headers, dict):
        raise ValueError("API request headers must be an object")
    header_names = {str(name).casefold() for name in headers}
    if isolation.mode == "namespace":
        injection = isolation.namespace
        if injection is None:
            raise ValueError("namespace isolation declaration is incomplete")
        if injection.location == "header":
            if injection.name.casefold() in header_names:
                raise ValueError("API request must not override the namespace header")
        else:
            target = request.get(injection.location)
            if not isinstance(target, dict):
                raise ValueError(
                    f"namespace {injection.location} injection requires a root JSON object"
                )
            if injection.name in target:
                raise ValueError(
                    f"API request must not override the namespace {injection.location} field"
                )
    if operation_policy.classification == "mutation_idempotent":
        header = str(operation_policy.idempotency_header)
        if header.casefold() in header_names:
            raise ValueError("API request must not supply the managed idempotency header")


def apply_runtime_request_policies(
    request: dict[str, Any],
    *,
    isolation: ApiIsolationPolicy,
    namespace_value: str | None,
    operation_policy: ApiOperationPolicy,
    idempotency_key: str | None,
) -> dict[str, Any]:
    validate_request_policy_compatibility(
        request,
        isolation=isolation,
        operation_policy=operation_policy,
    )
    headers = dict(request.get("headers") or {})
    request["headers"] = headers
    if isolation.mode == "namespace":
        injection = isolation.namespace
        if injection is None or namespace_value is None:
            raise ValueError("namespace isolation runtime value is unavailable")
        if injection.location == "header":
            headers[injection.name] = namespace_value
        else:
            target = dict(request.get(injection.location) or {})
            target[injection.name] = namespace_value
            request[injection.location] = target
    if operation_policy.classification == "mutation_idempotent":
        if idempotency_key is None:
            raise ValueError("managed idempotency key is unavailable")
        headers[str(operation_policy.idempotency_header)] = idempotency_key
    return request
