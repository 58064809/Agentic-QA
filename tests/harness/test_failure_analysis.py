from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from harness.domain.schemas.log_analysis import AnalyzeFailureCommand, LogAnalysis
from harness.domain.schemas.log_evidence import (
    LogEvidenceBundle,
    LogEvidenceStats,
    LogQueryRequest,
    NormalizedLogEntry,
)
from harness.infrastructure.failure_analysis import FilesystemFailureAnalysisService
from harness.infrastructure.persistence.common import create_only_json
from harness.infrastructure.persistence.filesystem import FilesystemStore

UTC = timezone.utc


def test_deterministic_analysis_aggregates_exception_and_timeout(tmp_path) -> None:
    now = datetime.now(tz=UTC).replace(microsecond=0)
    store = FilesystemStore(tmp_path)
    workspace = store.init_workspace("workspace-1", quality_policies=[])
    root = workspace / "executions" / "execution-1" / "triage" / "collections" / "collection-a"
    root.mkdir(parents=True)
    query = LogQueryRequest(
        workspace_id="workspace-1",
        execution_id="execution-1",
        case_id="CASE-1::dataset-a",
        dataset_id="dataset-a",
        environment="qa",
        api_service="order-api",
        services=["order-service"],
        started_at=now,
        completed_at=now + timedelta(seconds=1),
        max_entries=1000,
        trace_id="trace-42",
    )
    entries = [
        NormalizedLogEntry(
            entry_id=f"LOG-{index:06d}",
            timestamp=now,
            service="order-service",
            level="ERROR",
            message=(
                "java.sql.SQLException: query timeout id=12345\n"
                " at com.example.OrderRepository.find(OrderRepository.java:42)"
            ),
            trace_id="trace-42",
            source_ref=f"local-logs/order-service/app.log:{index}",
        )
        for index in range(1, 501)
    ]
    payload = {
        "schema_version": "agentic-qa.log-evidence.v1",
        "collection_id": "collection-a",
        "execution_id": "execution-1",
        "case_id": "CASE-1::dataset-a",
        "dataset_id": "dataset-a",
        "execution_evidence_sha256": "a" * 64,
        "provider": "local-file",
        "provider_structure_sha256": "b" * 64,
        "query": query.model_dump(mode="json"),
        "status": "success",
        "entries": [item.model_dump(mode="json") for item in entries],
        "diagnostics": [],
        "stats": LogEvidenceStats(
            entry_count=500,
            service_counts={"order-service": 500},
            level_counts={"ERROR": 500},
            redaction_count=0,
        ).model_dump(mode="json"),
    }
    content_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    bundle = LogEvidenceBundle.model_validate({**payload, "content_sha256": content_hash})
    evidence_path = root / "log-evidence.json"
    create_only_json(evidence_path, bundle.model_dump(mode="json"))
    create_only_json(
        root / "collection-manifest.json",
        {"log_evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest()},
    )

    result = FilesystemFailureAnalysisService(store).analyze(
        AnalyzeFailureCommand(workspace_id="workspace-1", execution_id="execution-1")
    )
    analysis_path = workspace / result.analyses[0].log_analysis_path
    analysis = LogAnalysis.model_validate_json(analysis_path.read_text(encoding="utf-8"))

    assert result.analyses[0].analysis_status == "success"
    assert len(analysis.signals) == 1
    assert analysis.signals[0].category == "exception"
    assert analysis.signals[0].exception_type == "java.sql.SQLException"
    assert analysis.signals[0].occurrence_count == 500
    assert analysis.signals[0].sample_refs == [f"LOG-{index:06d}" for index in range(1, 11)]
    assert "12345" not in analysis.signals[0].normalized_message
    assert len(analysis.timeline) == 501


def test_analysis_rejects_log_evidence_hash_drift(tmp_path) -> None:
    store = FilesystemStore(tmp_path)
    workspace = store.init_workspace("workspace-1", quality_policies=[])
    root = workspace / "executions" / "execution-1" / "triage" / "collections" / "collection-a"
    root.mkdir(parents=True)
    (root / "log-evidence.json").write_text("{}", encoding="utf-8")
    create_only_json(root / "collection-manifest.json", {"log_evidence_sha256": "0" * 64})

    import pytest

    with pytest.raises(ValueError, match="hash does not match"):
        FilesystemFailureAnalysisService(store).analyze(
            AnalyzeFailureCommand(
                workspace_id="workspace-1",
                execution_id="execution-1",
                collection_id="collection-a",
            )
        )


def test_analysis_requires_collection_id_when_case_has_multiple_collections(
    tmp_path,
) -> None:
    store = FilesystemStore(tmp_path)
    workspace = store.init_workspace("workspace-1", quality_policies=[])
    roots = [
        workspace / "executions" / "execution-1" / "triage" / "collections" / name
        for name in ("collection-a", "collection-b")
    ]
    for root in roots:
        root.mkdir(parents=True)
        (root / "log-evidence.json").write_text(_minimal_log_bundle(root.name), encoding="utf-8")

    import pytest

    with pytest.raises(ValueError, match="specify collection_id"):
        FilesystemFailureAnalysisService(store).analyze(
            AnalyzeFailureCommand(workspace_id="workspace-1", execution_id="execution-1")
        )


def _minimal_log_bundle(collection_id: str) -> str:
    now = datetime.now(tz=UTC).replace(microsecond=0)
    query = LogQueryRequest(
        workspace_id="workspace-1",
        execution_id="execution-1",
        case_id="CASE-1",
        environment="qa",
        api_service="order-api",
        services=["order-service"],
        started_at=now,
        completed_at=now,
        max_entries=10,
    )
    payload = {
        "schema_version": "agentic-qa.log-evidence.v1",
        "collection_id": collection_id,
        "execution_id": "execution-1",
        "case_id": "CASE-1",
        "execution_evidence_sha256": "a" * 64,
        "provider": "local-file",
        "provider_structure_sha256": "b" * 64,
        "query": query.model_dump(mode="json"),
        "status": "empty",
        "entries": [],
        "diagnostics": [],
        "stats": {
            "entry_count": 0,
            "service_counts": {},
            "level_counts": {},
            "redaction_count": 0,
        },
    }
    payload["content_sha256"] = hashlib.sha256(
        json.dumps(
            LogEvidenceBundle.model_construct(
                **{
                    **payload,
                    "query": query,
                    "stats": LogEvidenceStats.model_validate(payload["stats"]),
                },
                content_sha256="0" * 64,
            ).model_dump(mode="json", exclude={"content_sha256"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return json.dumps(payload)
