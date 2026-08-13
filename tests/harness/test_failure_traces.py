from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from harness.domain.schemas.local_config import LocalTracesConfig
from harness.domain.schemas.trace_evidence import TraceQueryRequest
from harness.infrastructure.failure_traces import LocalTraceProvider, build_trace_evidence


def _config() -> LocalTracesConfig:
    return LocalTracesConfig.model_validate(
        {
            "provider": "local-file",
            "allowed_environments": ["qa"],
            "local_file": {"root": "local-traces", "max_file_bytes": 1024 * 1024},
        }
    )


def _query(now: datetime, trace_id: str = "trace-001") -> TraceQueryRequest:
    return TraceQueryRequest(
        workspace_id="workspace-1",
        execution_id="execution-1",
        case_id="CASE-1",
        environment="qa",
        trace_id=trace_id,
        started_at=now,
        completed_at=now + timedelta(seconds=1),
    )


def test_local_trace_provider_reads_only_canonical_fixture(tmp_path) -> None:
    now = datetime.now(tz=UTC).replace(microsecond=0)
    root = tmp_path / "local-traces"
    root.mkdir()
    (root / "trace-001.json").write_text(
        json.dumps(
            {
                "schema_version": "agentic-qa.local-trace-fixture.v1",
                "trace_id": "trace-001",
                "spans": [
                    {
                        "trace_id": "trace-001",
                        "span_id": "span-b",
                        "parent_span_id": "span-a",
                        "service": "inventory-service",
                        "operation": "SELECT inventory",
                        "span_kind": "client",
                        "started_at": (now + timedelta(milliseconds=20)).isoformat(),
                        "ended_at": (now + timedelta(milliseconds=80)).isoformat(),
                        "status": "error",
                        "error_type": "DEADLINE_EXCEEDED",
                        "db_system": "mysql",
                        "peer_service": "mysql",
                    },
                    {
                        "trace_id": "trace-001",
                        "span_id": "span-a",
                        "service": "gateway",
                        "operation": "GET /orders",
                        "span_kind": "server",
                        "started_at": now.isoformat(),
                        "ended_at": (now + timedelta(milliseconds=100)).isoformat(),
                        "status": "error",
                        "http_status_code": 500,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    query = _query(now)
    result = LocalTraceProvider(tmp_path, _config()).get_trace(query)
    assert result.status == "success"
    bundle = build_trace_evidence(
        collection_id="collection-1",
        execution_sha="a" * 64,
        provider_sha="b" * 64,
        query=query,
        result=result,
        created_at=now,
    )
    assert [(span.evidence_ref, span.span_id) for span in bundle.spans] == [
        ("TRACE-000001", "span-a"),
        ("TRACE-000002", "span-b"),
    ]
    assert bundle.root_span_ref == "TRACE-000001"


def test_local_trace_provider_fails_closed_for_invalid_fixture(tmp_path) -> None:
    now = datetime.now(tz=UTC)
    root = tmp_path / "local-traces"
    root.mkdir()
    (root / "trace-001.json").write_text(
        '{"schema_version":"vendor.trace.v1","trace_id":"trace-001","spans":[]}',
        encoding="utf-8",
    )
    result = LocalTraceProvider(tmp_path, _config()).get_trace(_query(now))
    assert result.status == "failed"
    assert result.diagnostics[0].code == "TRACE_FIXTURE_INVALID"


def test_local_trace_provider_reports_not_found_without_search(tmp_path) -> None:
    (tmp_path / "local-traces").mkdir()
    result = LocalTraceProvider(tmp_path, _config()).get_trace(
        _query(datetime.now(tz=UTC), "missing")
    )
    assert result.status == "not_found"
