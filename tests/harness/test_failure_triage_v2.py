from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from harness.domain.schemas.execution_evidence import (
    CaseExecutionEvidence,
    ExecutionEnvironment,
    ExecutionEvidence,
    ExecutionSummary,
)
from harness.domain.schemas.failure_triage import FailureTriageProposal, FailureTriageV2
from harness.domain.schemas.log_analysis import AnalyzeFailureCommand, LogAnalysis, LogSignal
from harness.domain.schemas.log_evidence import (
    LogEvidenceBundle,
    LogEvidenceStats,
    LogQueryRequest,
    NormalizedLogEntry,
)
from harness.infrastructure.failure_triage_service import FilesystemFailureTriageService
from harness.infrastructure.llm.gateway import CallableModelGateway
from harness.infrastructure.persistence.common import create_only_json
from harness.infrastructure.persistence.filesystem import FilesystemStore

UTC = timezone.utc


def _fixture(tmp_path):
    now = datetime.now(tz=UTC).replace(microsecond=0)
    store = FilesystemStore(tmp_path)
    workspace = store.init_workspace("workspace-1", quality_policies=[])
    execution_root = workspace / "executions" / "execution-1"
    root = execution_root / "triage" / "collections" / "collection-a"
    root.mkdir(parents=True)
    evidence = ExecutionEvidence(
        schema_version="agentic-qa.execution-evidence.v2",
        run_id="execution-1",
        source_cases_path="published/api_test_draft/history/cases.yml",
        source_cases_schema_version="agentic-qa.api-cases.v1.2",
        started_at=now,
        completed_at=now,
        environment=ExecutionEnvironment(
            name="qa",
            base_url_env="BASE_URL",
            base_url_configured=True,
            allowed_methods=["GET"],
            request_timeout_seconds=10,
        ),
        summary=ExecutionSummary(total=1, executed=1, passed=0, failed=1, errors=0, blocked=0),
        cases=[
            CaseExecutionEvidence(
                case_id="CASE-1",
                title="failed request",
                method="GET",
                path="/orders",
                status="failed",
                started_at=now,
                completed_at=now,
                duration_ms=1,
                status_code=500,
                request_dispatched=True,
            )
        ],
    )
    create_only_json(execution_root / "evidence.json", evidence.model_dump(mode="json"))
    query = LogQueryRequest(
        workspace_id="workspace-1",
        execution_id="execution-1",
        case_id="CASE-1",
        environment="qa",
        api_service="order-api",
        services=["order-service"],
        started_at=now,
        completed_at=now,
        max_entries=100,
    )
    entry = NormalizedLogEntry(
        entry_id="LOG-000001",
        timestamp=now,
        service="order-service",
        level="ERROR",
        message="java.sql.SQLException database unavailable",
        exception_type="java.sql.SQLException",
        source_ref="local-logs/order-service/app.log:1",
    )
    log_payload = {
        "schema_version": "agentic-qa.log-evidence.v1",
        "collection_id": "collection-a",
        "execution_id": "execution-1",
        "case_id": "CASE-1",
        "execution_evidence_sha256": "a" * 64,
        "provider": "local-file",
        "provider_structure_sha256": "b" * 64,
        "query": query.model_dump(mode="json"),
        "status": "success",
        "entries": [entry.model_dump(mode="json")],
        "diagnostics": [],
        "stats": LogEvidenceStats(
            entry_count=1,
            service_counts={"order-service": 1},
            level_counts={"ERROR": 1},
            redaction_count=0,
        ).model_dump(mode="json"),
    }
    log_draft = LogEvidenceBundle.model_construct(
        **{
            **log_payload,
            "query": query,
            "entries": [entry],
            "stats": LogEvidenceStats(
                entry_count=1,
                service_counts={"order-service": 1},
                level_counts={"ERROR": 1},
                redaction_count=0,
            ),
        },
        content_sha256="0" * 64,
    )
    canonical_log = log_draft.model_dump(mode="json", exclude={"content_sha256"})
    log_content_sha = hashlib.sha256(
        json.dumps(canonical_log, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    logs = LogEvidenceBundle.model_validate({**log_payload, "content_sha256": log_content_sha})
    log_path = root / "log-evidence.json"
    create_only_json(log_path, logs.model_dump(mode="json"))
    signal = LogSignal(
        signal_id="SIGNAL-0001",
        category="exception",
        service="order-service",
        fingerprint="c" * 64,
        exception_type="java.sql.SQLException",
        normalized_message="java.sql.SQLException database unavailable",
        occurrence_count=1,
        first_seen=now,
        last_seen=now,
        sample_refs=["LOG-000001"],
    )
    analysis_payload = {
        "schema_version": "agentic-qa.log-analysis.v1",
        "collection_id": "collection-a",
        "execution_id": "execution-1",
        "case_id": "CASE-1",
        "log_evidence_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        "signals": [signal.model_dump(mode="json")],
        "timeline": [],
    }
    analysis_draft = LogAnalysis.model_construct(
        **{**analysis_payload, "signals": [signal]}, content_sha256="0" * 64
    )
    canonical_analysis = analysis_draft.model_dump(mode="json", exclude={"content_sha256"})
    analysis_sha = hashlib.sha256(
        json.dumps(canonical_analysis, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    analysis = LogAnalysis.model_validate({**analysis_payload, "content_sha256": analysis_sha})
    create_only_json(root / "log-analysis.json", analysis.model_dump(mode="json"))
    create_only_json(
        root / "collection-manifest.json",
        {"log_evidence_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest()},
    )
    return store, workspace, root


def test_triage_revises_unsupported_service_once(tmp_path) -> None:
    store, workspace, root = _fixture(tmp_path)
    calls = 0

    def callback(**_kwargs):
        nonlocal calls
        calls += 1
        service = "invented-service" if calls == 1 else "order-service"
        return FailureTriageProposal.model_validate(
            {
                "primary": {
                    "category": "database",
                    "service": service,
                    "exception_type": "java.sql.SQLException",
                    "summary": "database unavailable",
                    "confidence": 0.91,
                    "evidence_refs": ["LOG-000001"],
                },
                "recommended_actions": ["Inspect database availability"],
            }
        )

    service = FilesystemFailureTriageService.__new__(FilesystemFailureTriageService)
    service._store = store
    service._model = CallableModelGateway(callback)
    service._analysis = _ExistingAnalysis(workspace)
    result = service.analyze(
        AnalyzeFailureCommand(
            workspace_id="workspace-1",
            execution_id="execution-1",
            collection_id="collection-a",
        )
    )
    triage = FailureTriageV2.model_validate_json(
        (root / "failure-triage.json").read_text(encoding="utf-8")
    )

    assert calls == 2
    assert result.analyses[0].triage_status == "success"
    assert triage.likelihood == "highly_likely"
    assert triage.primary and triage.primary.service == "order-service"


def test_triage_model_failure_is_persisted_without_execution_mutation(tmp_path) -> None:
    store, workspace, root = _fixture(tmp_path)
    evidence_path = workspace / "executions" / "execution-1" / "evidence.json"
    before = evidence_path.read_bytes()

    def callback(**_kwargs):
        raise TimeoutError("model timeout")

    service = FilesystemFailureTriageService.__new__(FilesystemFailureTriageService)
    service._store = store
    service._model = CallableModelGateway(callback)
    service._analysis = _ExistingAnalysis(workspace)
    result = service.analyze(
        AnalyzeFailureCommand(
            workspace_id="workspace-1",
            execution_id="execution-1",
            collection_id="collection-a",
        )
    )
    triage = FailureTriageV2.model_validate_json(
        (root / "failure-triage.json").read_text(encoding="utf-8")
    )

    assert result.analyses[0].triage_status == "failed"
    assert triage.primary is None
    assert evidence_path.read_bytes() == before


class _ExistingAnalysis:
    def __init__(self, workspace) -> None:
        self._workspace = workspace

    def analyze(self, command):
        from harness.domain.schemas.log_analysis import (
            AnalyzeFailureResult,
            FailureAnalysisItem,
        )

        return AnalyzeFailureResult(
            workspace_id=command.workspace_id,
            execution_id=command.execution_id,
            analyses=[
                FailureAnalysisItem(
                    collection_id="collection-a",
                    case_id="CASE-1",
                    analysis_status="success",
                    log_analysis_path=(
                        "executions/execution-1/triage/collections/collection-a/log-analysis.json"
                    ),
                )
            ],
        )
