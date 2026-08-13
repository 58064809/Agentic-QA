from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from harness.domain.schemas.trace_evidence import (
    NormalizedTraceSpan,
    TraceEvidenceBundle,
    TraceQueryRequest,
)
from harness.infrastructure.failure_trace_analysis import derive_trace_analysis

UTC = timezone.utc


def _bundle(specs: list[dict]) -> TraceEvidenceBundle:
    now = datetime.now(tz=UTC).replace(microsecond=0)
    spans = []
    for index, spec in enumerate(specs, 1):
        started = now + timedelta(milliseconds=spec.pop("offset", index))
        duration = spec.pop("duration", 10)
        values = {
            "evidence_ref": f"TRACE-{index:06d}",
            "trace_id": "trace-1",
            "started_at": started,
            "ended_at": started + timedelta(milliseconds=duration),
            "duration_ms": duration,
            "operation": "operation",
            "span_kind": "internal",
            "status": "unset",
            **spec,
        }
        spans.append(NormalizedTraceSpan.model_validate(values))
    query = TraceQueryRequest(
        workspace_id="workspace-1",
        execution_id="execution-1",
        case_id="CASE-1",
        environment="qa",
        trace_id="trace-1",
        started_at=now,
        completed_at=now + timedelta(seconds=1),
    )
    values = {
        "collection_id": "collection-1",
        "execution_id": "execution-1",
        "case_id": "CASE-1",
        "trace_id": "trace-1",
        "execution_evidence_sha256": "a" * 64,
        "provider": "local-file",
        "provider_structure_sha256": "b" * 64,
        "query": query,
        "status": "success",
        "spans": spans,
        "root_span_ref": next(
            (span.evidence_ref for span in spans if not span.parent_span_id), None
        ),
        "created_at": now,
    }
    payload = TraceEvidenceBundle.model_construct(**values, content_sha256="0" * 64).model_dump(
        mode="json", exclude={"content_sha256"}
    )
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return TraceEvidenceBundle.model_validate({**payload, "content_sha256": digest})


def test_trace_analysis_finds_dependency_timeout_and_paths() -> None:
    bundle = _bundle(
        [
            {"span_id": "root", "service": "gateway", "status": "error", "duration": 100},
            {
                "span_id": "order",
                "parent_span_id": "root",
                "service": "order-service",
                "status": "error",
                "duration": 80,
            },
            {
                "span_id": "mysql",
                "parent_span_id": "order",
                "service": "inventory-service",
                "span_kind": "client",
                "status": "error",
                "error_type": "DEADLINE_EXCEEDED",
                "db_system": "mysql",
                "peer_service": "mysql",
                "duration": 70,
            },
        ]
    )
    analysis = derive_trace_analysis(bundle, "c" * 64)
    assert analysis.primary_failure is not None
    assert analysis.primary_failure.service == "inventory-service"
    assert analysis.primary_failure.dependency == "mysql"
    assert analysis.primary_failure.failure_type == "timeout"
    assert analysis.propagation_chain == [
        "TRACE-000003",
        "TRACE-000002",
        "TRACE-000001",
    ]
    assert analysis.critical_path == [
        "TRACE-000001",
        "TRACE-000002",
        "TRACE-000003",
    ]
    assert analysis.critical_path_duration_ms == 250
    assert analysis.slowest_span_ref == "TRACE-000001"


def test_multiple_roots_degrades_without_selecting_cause() -> None:
    analysis = derive_trace_analysis(
        _bundle(
            [
                {"span_id": "root-a", "service": "a", "status": "error"},
                {"span_id": "root-b", "service": "b", "status": "error"},
            ]
        ),
        "c" * 64,
    )
    assert analysis.analysis_status == "degraded"
    assert "multiple_roots" in analysis.diagnostics
    assert analysis.primary_failure is None
    assert analysis.critical_path == []


def test_orphan_is_diagnostic_but_valid_root_still_analyzes() -> None:
    analysis = derive_trace_analysis(
        _bundle(
            [
                {"span_id": "root", "service": "gateway", "status": "ok"},
                {
                    "span_id": "orphan",
                    "parent_span_id": "missing",
                    "service": "inventory",
                    "status": "error",
                },
            ]
        ),
        "c" * 64,
    )
    assert analysis.analysis_status == "degraded"
    assert analysis.first_error_span_ref == "TRACE-000002"
    assert analysis.primary_failure is None
    assert analysis.root_span_ref == "TRACE-000001"


def test_slow_success_is_not_a_root_cause() -> None:
    analysis = derive_trace_analysis(
        _bundle([{"span_id": "root", "service": "gateway", "status": "ok", "duration": 3000}]),
        "c" * 64,
    )
    assert analysis.slowest_span_ref == "TRACE-000001"
    assert analysis.first_error_span_ref is None
    assert analysis.primary_failure is None
