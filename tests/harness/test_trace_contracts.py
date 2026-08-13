from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from harness.domain.schemas.trace_analysis import TraceAnalysis
from harness.domain.schemas.trace_evidence import (
    NormalizedTraceSpan,
    TraceEvidenceBundle,
    TraceQueryRequest,
)


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_trace_query_is_exact_bounded_and_ordered() -> None:
    now = datetime.now(tz=UTC)
    query = TraceQueryRequest(
        workspace_id="qa",
        execution_id="execution-1",
        case_id="CASE-1",
        environment="qa",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        started_at=now,
        completed_at=now + timedelta(seconds=1),
    )
    assert query.max_spans == 1000
    with pytest.raises(ValueError, match="completion cannot precede"):
        query.model_copy(update={"completed_at": now - timedelta(seconds=1)}).model_validate(
            query.model_copy(update={"completed_at": now - timedelta(seconds=1)}).model_dump()
        )


def test_trace_evidence_is_content_hash_protected() -> None:
    now = datetime.now(tz=UTC)
    query = TraceQueryRequest(
        workspace_id="qa",
        execution_id="execution-1",
        case_id="CASE-1",
        environment="qa",
        trace_id="trace-1",
        started_at=now,
        completed_at=now + timedelta(seconds=1),
    )
    span = NormalizedTraceSpan(
        evidence_ref="TRACE-000001",
        trace_id="trace-1",
        span_id="span-1",
        service="gateway",
        operation="GET /orders",
        span_kind="server",
        started_at=now,
        ended_at=now + timedelta(seconds=1),
        duration_ms=1000,
        status="error",
    )
    payload = {
        "schema_version": "agentic-qa.trace-evidence.v1",
        "collection_id": "collection-1",
        "execution_id": "execution-1",
        "case_id": "CASE-1",
        "dataset_id": None,
        "trace_id": "trace-1",
        "execution_evidence_sha256": "a" * 64,
        "provider": "local-file",
        "provider_structure_sha256": "b" * 64,
        "query": query.model_dump(mode="json"),
        "status": "success",
        "spans": [span.model_dump(mode="json")],
        "root_span_ref": "TRACE-000001",
        "diagnostics": [],
        "created_at": now.isoformat(),
    }
    normalized = TraceEvidenceBundle.model_construct(
        **{**payload, "query": query, "spans": [span], "created_at": now},
        content_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"content_sha256"})
    bundle = TraceEvidenceBundle.model_validate(
        {**normalized, "content_sha256": _digest(normalized)}
    )
    assert bundle.root_span_ref == "TRACE-000001"
    with pytest.raises(ValueError, match="content hash"):
        bundle.model_copy(update={"status": "failed"}).model_validate(
            bundle.model_copy(update={"status": "failed"}).model_dump()
        )


def test_trace_analysis_is_content_hash_protected() -> None:
    payload = {
        "schema_version": "agentic-qa.trace-analysis.v1",
        "collection_id": "collection-1",
        "execution_id": "execution-1",
        "case_id": "CASE-1",
        "dataset_id": None,
        "trace_evidence_sha256": "a" * 64,
        "analysis_status": "empty",
        "root_span_ref": None,
        "first_error_span_ref": None,
        "primary_failure": None,
        "propagation_chain": [],
        "critical_path": [],
        "critical_path_duration_ms": None,
        "slowest_span_ref": None,
        "dependency_failures": [],
        "diagnostics": [],
    }
    assert (
        TraceAnalysis.model_validate(
            {**payload, "content_sha256": _digest(payload)}
        ).analysis_status
        == "empty"
    )
