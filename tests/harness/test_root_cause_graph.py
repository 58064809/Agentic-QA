from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from harness.domain.schemas.log_analysis import LogAnalysis, LogSignal
from harness.domain.schemas.log_evidence import (
    LogEvidenceBundle,
    LogEvidenceStats,
    LogQueryRequest,
    NormalizedLogEntry,
)
from harness.domain.schemas.trace_evidence import NormalizedTraceSpan
from harness.infrastructure.root_cause_graph import build_root_cause_graph

UTC = timezone.utc


def _hashed(model, values):
    payload = model.model_construct(**values, content_sha256="0" * 64).model_dump(
        mode="json", exclude={"content_sha256"}
    )
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return model.model_validate({**payload, "content_sha256": digest})


def test_graph_uses_exact_span_correlation_and_is_deterministic() -> None:
    from harness.domain.schemas.trace_evidence import TraceEvidenceBundle, TraceQueryRequest

    now = datetime.now(tz=UTC).replace(microsecond=0)
    query = LogQueryRequest(
        workspace_id="workspace-1",
        execution_id="execution-1",
        case_id="CASE-1",
        environment="qa",
        api_service="orders",
        services=["inventory"],
        started_at=now,
        completed_at=now + timedelta(seconds=1),
        max_entries=10,
        trace_id="trace-1",
    )
    entry = NormalizedLogEntry(
        entry_id="LOG-000001",
        timestamp=now,
        service="inventory",
        level="ERROR",
        message="database timeout",
        trace_id="trace-1",
        span_id="span-1",
        source_ref="fixture:1",
    )
    logs = _hashed(
        LogEvidenceBundle,
        {
            "collection_id": "collection-1",
            "execution_id": "execution-1",
            "case_id": "CASE-1",
            "execution_evidence_sha256": "a" * 64,
            "provider": "local-file",
            "provider_structure_sha256": "b" * 64,
            "query": query,
            "status": "success",
            "entries": [entry],
            "stats": LogEvidenceStats(
                entry_count=1,
                service_counts={"inventory": 1},
                level_counts={"ERROR": 1},
                redaction_count=0,
            ),
        },
    )
    analysis = _hashed(
        LogAnalysis,
        {
            "collection_id": "collection-1",
            "execution_id": "execution-1",
            "case_id": "CASE-1",
            "log_evidence_sha256": "c" * 64,
            "signals": [
                LogSignal(
                    signal_id="SIGNAL-0001",
                    category="database",
                    service="inventory",
                    fingerprint="d" * 64,
                    normalized_message="database timeout",
                    occurrence_count=1,
                    sample_refs=["LOG-000001"],
                )
            ],
        },
    )
    trace_query = TraceQueryRequest(
        workspace_id="workspace-1",
        execution_id="execution-1",
        case_id="CASE-1",
        environment="qa",
        trace_id="trace-1",
        started_at=now,
        completed_at=now + timedelta(seconds=1),
    )
    traces = _hashed(
        TraceEvidenceBundle,
        {
            "collection_id": "collection-1",
            "execution_id": "execution-1",
            "case_id": "CASE-1",
            "trace_id": "trace-1",
            "execution_evidence_sha256": "a" * 64,
            "provider": "local-file",
            "provider_structure_sha256": "e" * 64,
            "query": trace_query,
            "status": "success",
            "spans": [
                NormalizedTraceSpan(
                    evidence_ref="TRACE-000001",
                    trace_id="trace-1",
                    span_id="span-1",
                    service="inventory",
                    operation="mysql",
                    span_kind="client",
                    started_at=now,
                    ended_at=now + timedelta(milliseconds=50),
                    duration_ms=50,
                    status="error",
                )
            ],
            "root_span_ref": "TRACE-000001",
            "created_at": now,
        },
    )
    graph = build_root_cause_graph(
        collection_id="collection-1",
        execution_id="execution-1",
        case_id="CASE-1",
        dataset_id=None,
        execution_sha="a" * 64,
        logs=logs,
        log_analysis=analysis,
        log_analysis_sha="f" * 64,
        traces=traces,
        trace_analysis=None,
        trace_analysis_sha=None,
    )
    correlation = [edge for edge in graph.edges if edge.edge_type == "SPAN_CORROBORATED_BY_LOG"]
    assert len(correlation) == 1
    assert correlation[0].correlation_level == "strong"
    assert graph == build_root_cause_graph(
        collection_id="collection-1",
        execution_id="execution-1",
        case_id="CASE-1",
        dataset_id=None,
        execution_sha="a" * 64,
        logs=logs,
        log_analysis=analysis,
        log_analysis_sha="f" * 64,
        traces=traces,
        trace_analysis=None,
        trace_analysis_sha=None,
    )
