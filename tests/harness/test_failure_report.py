from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harness.domain.schemas.failure_triage import FailureHypothesis, FailureTriageV2
from harness.domain.schemas.log_analysis import PrepareFailureReportCommand
from harness.infrastructure.failure_report import FilesystemFailureReportService
from harness.infrastructure.persistence.common import create_only_json
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.quality import QualityStrategyRegistry
from harness.infrastructure.quality.generic import GenericArtifactStrategy
from harness.infrastructure.quality.normalization import SafeMarkdownNormalizer


def _triage_payload(
    category: str = "database",
    confidence: float = 0.9,
    *,
    execution_sha: str = "a" * 64,
    logs_sha: str = "b" * 64,
    analysis_sha: str = "c" * 64,
) -> dict:
    payload = {
        "schema_version": "agentic-qa.failure-triage.v2",
        "collection_id": "collection-a",
        "execution_id": "execution-1",
        "case_id": "CASE-1",
        "execution_evidence_sha256": execution_sha,
        "log_evidence_sha256": logs_sha,
        "log_analysis_sha256": analysis_sha,
        "triage_status": "success",
        "likelihood": "highly_likely" if confidence >= 0.9 else "probable",
        "primary": {
            "category": category,
            "service": "order-service",
            "summary": "database is unavailable",
            "confidence": confidence,
            "evidence_refs": ["LOG-000001"],
        },
        "alternatives": [],
        "recommended_actions": ["Inspect database availability"],
        "available_evidence_refs": ["EXEC-0001", "LOG-000001"],
    }
    draft = FailureTriageV2.model_construct(
        **{
            **payload,
            "primary": FailureHypothesis.model_validate(payload["primary"]),
        },
        content_sha256="0" * 64,
    )
    canonical = draft.model_dump(mode="json", exclude={"content_sha256"})
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**payload, "content_sha256": digest}


def _service(tmp_path: Path, category: str = "database"):
    store = FilesystemStore(tmp_path)
    workspace = store.init_workspace("workspace-1", quality_policies=[])
    execution = workspace / "executions" / "execution-1"
    collection = execution / "triage" / "collections" / "collection-a"
    collection.mkdir(parents=True)
    sources = {
        "evidence.json": {"schema_version": "agentic-qa.execution-evidence.v2"},
        "log-evidence.json": {"schema_version": "agentic-qa.log-evidence.v1"},
        "log-analysis.json": {"schema_version": "agentic-qa.log-analysis.v1"},
    }
    paths = {}
    for name, payload in sources.items():
        target = execution / name if name == "evidence.json" else collection / name
        create_only_json(target, payload)
        paths[name] = target
    create_only_json(
        collection / "failure-triage.json",
        _triage_payload(
            category,
            execution_sha=hashlib.sha256(paths["evidence.json"].read_bytes()).hexdigest(),
            logs_sha=hashlib.sha256(paths["log-evidence.json"].read_bytes()).hexdigest(),
            analysis_sha=hashlib.sha256(paths["log-analysis.json"].read_bytes()).hexdigest(),
        ),
    )
    registry = QualityStrategyRegistry()
    registry.register(GenericArtifactStrategy())
    registry.register_normalizer(SafeMarkdownNormalizer())
    return store, workspace, collection, FilesystemFailureReportService(store, registry)


def test_failure_report_creates_review_gated_analysis_and_bug_candidates(tmp_path: Path) -> None:
    store, workspace, collection, service = _service(tmp_path)
    result = service.prepare(
        PrepareFailureReportCommand(workspace_id="workspace-1", execution_id="execution-1")
    )

    report = result.reports[0]
    assert report.human_review_required is True
    assert report.candidate_artifacts == ["failure_analysis", "bug_draft"]
    snapshot = store.load_snapshot_read_only("workspace-1", report.run_id)
    assert snapshot.status == "needs_human_review"
    assert {item.artifact for item in snapshot.candidates} == {
        "failure_analysis",
        "bug_draft",
    }
    assert all(item.status == "needs_human_review" for item in snapshot.candidates)
    assert (collection / "bug-draft.json").is_file()
    for candidate in snapshot.candidates:
        assert {item.name for item in candidate.attachments} >= {
            "failure-triage.json",
            "log-analysis.json",
            "log-evidence.json",
        }
    with pytest.raises(FileNotFoundError):
        store.get_artifact_diff(
            __import__("harness").GetArtifactDiffQuery(
                workspace_id="workspace-1",
                run_id=report.run_id,
                artifact="bug_draft",
                before="published",
                after="raw",
            )
        )


def test_failure_report_gate_omits_bug_for_test_script(tmp_path: Path) -> None:
    store, _workspace, collection, service = _service(tmp_path, "test-script")
    result = service.prepare(
        PrepareFailureReportCommand(workspace_id="workspace-1", execution_id="execution-1")
    )

    report = result.reports[0]
    assert report.candidate_artifacts == ["failure_analysis"]
    snapshot = store.load_snapshot_read_only("workspace-1", report.run_id)
    assert [item.artifact for item in snapshot.candidates] == ["failure_analysis"]
    assert not (collection / "bug-draft.json").exists()


def test_failure_report_rejects_tampered_source_before_candidate(tmp_path: Path) -> None:
    store, _workspace, collection, service = _service(tmp_path)
    (collection / "log-analysis.json").write_text('{"tampered":true}', encoding="utf-8")

    with pytest.raises(ValueError, match="source hash"):
        service.prepare(
            PrepareFailureReportCommand(workspace_id="workspace-1", execution_id="execution-1")
        )

    runs = tmp_path / "workspaces" / "workspace-1" / "runs"
    assert not list(runs.iterdir())
