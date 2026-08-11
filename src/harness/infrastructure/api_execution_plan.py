from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from harness.domain.models import (
    ApiAuthentication,
    ApiIsolationPolicy,
    ApiOperationPolicy,
    ExecutionProfile,
    resolve_api_operation_policy,
)
from harness.domain.schemas.api_execution_reporting import (
    ApiExecutionPlan,
    ApiExecutionPlanCase,
    ApiExecutionPlanCleanup,
)
from harness.domain.schemas.api_test_cases import (
    ApiTestCase,
    parse_api_case_variables,
    parse_api_cleanup_steps,
)
from harness.infrastructure.api_runtime_policy import (
    derive_execution_namespace,
    derive_idempotency_key,
)

UTC = timezone.utc


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_api_execution_plan(
    *,
    workspace_id: str,
    execution_id: str,
    service: str,
    environment: str,
    source_cases_path: str,
    source_cases_sha256: str,
    source_publication_id: str,
    source_history_path: str,
    structural_sha256: str,
    policy_sha256: str,
    profile: ExecutionProfile,
    authentication: ApiAuthentication | None,
    isolation: ApiIsolationPolicy,
    operation_policies: dict[str, ApiOperationPolicy],
    cases: list[ApiTestCase],
) -> ApiExecutionPlan:
    planned_cases: list[ApiExecutionPlanCase] = []
    for case in cases:
        variables = parse_api_case_variables(case.variables)
        cleanup_steps = parse_api_cleanup_steps(case.cleanup)
        cleanup_ids = [step.id for step in cleanup_steps]
        datasets = variables.datasets or [None]
        request_sha256 = _canonical_sha256(case.request.model_dump(mode="json"))
        for dataset in datasets:
            case_id = case.id if dataset is None else f"{case.id}::{dataset.id}"
            operation_policy = resolve_api_operation_policy(
                operation_policies,
                case.request.method,
                case.request.path,
            )
            idempotency_key = (
                derive_idempotency_key(
                    execution_id,
                    case_id,
                    str(case.request.method),
                    str(case.request.path),
                    prefix=operation_policy.idempotency_key_prefix,
                )
                if operation_policy.classification == "mutation_idempotent"
                else None
            )
            planned_cleanups: list[ApiExecutionPlanCleanup] = []
            for step in cleanup_steps:
                cleanup_case_id = f"{case_id}::cleanup::{step.id}"
                cleanup_policy = resolve_api_operation_policy(
                    operation_policies,
                    step.request.method,
                    step.request.path,
                )
                cleanup_key = (
                    derive_idempotency_key(
                        execution_id,
                        cleanup_case_id,
                        step.request.method,
                        step.request.path,
                        prefix=cleanup_policy.idempotency_key_prefix,
                    )
                    if cleanup_policy.classification == "mutation_idempotent"
                    else None
                )
                planned_cleanups.append(
                    ApiExecutionPlanCleanup(
                        cleanup_id=step.id,
                        method=step.request.method,
                        path_template=step.request.path,
                        request_structure_sha256=_canonical_sha256(
                            step.request.model_dump(mode="json")
                        ),
                        operation_classification=cleanup_policy.classification,
                        idempotency_header=cleanup_policy.idempotency_header,
                        idempotency_key_sha256=(
                            hashlib.sha256(cleanup_key.encode()).hexdigest()
                            if cleanup_key is not None
                            else None
                        ),
                    )
                )
            planned_cases.append(
                ApiExecutionPlanCase(
                    case_id=case_id,
                    source_case_id=case.id,
                    dataset_id=None if dataset is None else dataset.id,
                    method=case.request.method,
                    path_template=case.request.path,
                    contract_status=case.contract_status,
                    request_structure_sha256=request_sha256,
                    cleanup_ids=cleanup_ids,
                    cleanups=planned_cleanups,
                    operation_classification=operation_policy.classification,
                    idempotency_header=operation_policy.idempotency_header,
                    idempotency_key_sha256=(
                        hashlib.sha256(idempotency_key.encode()).hexdigest()
                        if idempotency_key is not None
                        else None
                    ),
                )
            )
    namespace = isolation.namespace
    namespace_value = (
        derive_execution_namespace(execution_id, prefix=namespace.prefix)
        if isolation.mode == "namespace" and namespace is not None
        else None
    )
    payload: dict[str, Any] = {
        "schema_version": "agentic-qa.api-execution-plan.v2",
        "workspace_id": workspace_id,
        "execution_id": execution_id,
        "service": service,
        "environment": environment,
        "created_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "source_cases_path": source_cases_path,
        "source_cases_sha256": source_cases_sha256,
        "source_publication_id": source_publication_id,
        "source_history_path": source_history_path,
        "structural_sha256": structural_sha256,
        "policy_sha256": policy_sha256,
        "execution_profile_sha256": _canonical_sha256(profile.model_dump(mode="json")),
        "authentication_mode": "none" if authentication is None else authentication.mode,
        "isolation_mode": isolation.mode,
        "namespace_location": namespace.location if namespace is not None else None,
        "namespace_name": namespace.name if namespace is not None else None,
        "namespace_value_sha256": (
            hashlib.sha256(namespace_value.encode()).hexdigest()
            if namespace_value is not None
            else None
        ),
        "cases": [item.model_dump(mode="json") for item in planned_cases],
    }
    payload["plan_sha256"] = _canonical_sha256(payload)
    return ApiExecutionPlan.model_validate(payload)
