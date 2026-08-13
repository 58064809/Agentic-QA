from __future__ import annotations

import hashlib
import json
from pathlib import Path

from harness.application.failure_triage_engine import (
    SYSTEM as ENGINE_SYSTEM,
)
from harness.application.failure_triage_engine import (
    FailureTriageContext,
    FailureTriageEngine,
)
from harness.domain.schemas.execution_evidence import load_execution_evidence
from harness.domain.schemas.failure_triage import FailureHypothesis, FailureTriageV2
from harness.domain.schemas.log_analysis import (
    AnalyzeFailureCommand,
    AnalyzeFailureResult,
    LogAnalysis,
)
from harness.domain.schemas.log_evidence import LogEvidenceBundle
from harness.domain.schemas.trace_analysis import RootCauseEvidenceGraph, TraceAnalysis
from harness.domain.schemas.trace_evidence import TraceEvidenceBundle
from harness.infrastructure.failure_analysis import FilesystemFailureAnalysisService
from harness.infrastructure.failure_collection import FilesystemFailureEvidenceCollector
from harness.infrastructure.failure_report import FilesystemFailureReportService
from harness.infrastructure.persistence.common import create_only_json
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.root_cause_graph import build_root_cause_graph

SYSTEM = ENGINE_SYSTEM


class FilesystemFailureTriageService:
    def __init__(self, store: FilesystemStore, model, local_config, quality) -> None:
        self._store = store
        self._model = model
        self._engine = FailureTriageEngine(model)
        self._analysis = FilesystemFailureAnalysisService(store)
        self._collector = FilesystemFailureEvidenceCollector(store, local_config)
        self._reports = FilesystemFailureReportService(store, quality)

    def collect(self, command):
        return self._collector.collect_logs(command)

    def collect_evidence(self, command):
        return self._collector.collect(command)

    def prepare_report(self, command):
        return self._reports.prepare(command)

    def analyze(self, command: AnalyzeFailureCommand) -> AnalyzeFailureResult:
        deterministic = self._analysis.analyze(command)
        workspace_root = self._store.require_workspace(command.workspace_id).resolve()
        items = [self._triage_one(item, workspace_root, command) for item in deterministic.analyses]
        return deterministic.model_copy(update={"analyses": items})

    def _triage_one(self, item, workspace_root: Path, command: AnalyzeFailureCommand):
        root = (workspace_root / item.log_analysis_path).parent
        target = root / "failure-triage.json"
        if target.exists():
            triage = FailureTriageV2.model_validate_json(target.read_text(encoding="utf-8"))
            self._validate_linked_hashes(root, triage, workspace_root, command.execution_id)
            return item.model_copy(
                update={
                    "triage_status": triage.triage_status,
                    "failure_triage_path": target.relative_to(workspace_root).as_posix(),
                }
            )
        execution_path = workspace_root / "executions" / command.execution_id / "evidence.json"
        execution_bytes = execution_path.read_bytes()
        execution = load_execution_evidence(execution_bytes)
        case = next((value for value in execution.cases if value.case_id == item.case_id), None)
        if case is None:
            raise ValueError("triage case is absent from execution evidence")
        exec_facts = [
            {
                "ref": "EXEC-0001",
                "fact": {
                    "case_id": case.case_id,
                    "dataset_id": case.dataset_id,
                    "method": case.method,
                    "path_template": case.path,
                    "status": case.status,
                    "status_code": case.status_code,
                    "request_dispatched": case.request_dispatched,
                    "error": case.error,
                },
            },
            *[
                {
                    "ref": f"EXEC-{index:04d}",
                    "fact": {
                        "assertion_type": assertion.type,
                        "passed": assertion.passed,
                        "path": assertion.path,
                        "message": assertion.message,
                    },
                }
                for index, assertion in enumerate(case.assertions, 2)
            ],
        ]
        logs, log_analysis, log_bytes, analysis_bytes = self._optional_logs(root)
        traces, trace_analysis, trace_bytes, trace_analysis_bytes = self._optional_traces(root)
        graph_path = root / "root-cause-graph.json"
        if not graph_path.exists():
            graph_value = build_root_cause_graph(
                collection_id=(log_analysis or trace_analysis).collection_id,
                execution_id=(log_analysis or trace_analysis).execution_id,
                case_id=(log_analysis or trace_analysis).case_id,
                dataset_id=(log_analysis or trace_analysis).dataset_id,
                execution_sha=hashlib.sha256(execution_bytes).hexdigest(),
                logs=logs,
                log_analysis=log_analysis,
                log_analysis_sha=(
                    hashlib.sha256(analysis_bytes).hexdigest() if analysis_bytes else None
                ),
                traces=traces,
                trace_analysis=trace_analysis,
                trace_analysis_sha=(
                    hashlib.sha256(trace_analysis_bytes).hexdigest()
                    if trace_analysis_bytes
                    else None
                ),
            )
            create_only_json(graph_path, graph_value.model_dump(mode="json"))
        graph_bytes = graph_path.read_bytes()
        graph = RootCauseEvidenceGraph.model_validate_json(graph_bytes)
        log_facts = []
        log_services: set[str] = set()
        log_exceptions: set[str] = set()
        log_refs: list[str] = []
        if log_analysis:
            log_services = {signal.service for signal in log_analysis.signals}
            log_exceptions = {
                signal.exception_type for signal in log_analysis.signals if signal.exception_type
            }
            log_refs = sorted(
                {ref for signal in log_analysis.signals for ref in signal.sample_refs}
            )
            log_facts = [
                {
                    "signal_id": signal.signal_id,
                    "category": signal.category,
                    "service": signal.service,
                    "exception_type": signal.exception_type,
                    "normalized_message": signal.normalized_message,
                    "occurrence_count": signal.occurrence_count,
                    "evidence_refs": signal.sample_refs,
                }
                for signal in log_analysis.signals
            ]
        trace_claims = {}
        trace_facts = []
        if traces:
            failures = trace_analysis.dependency_failures if trace_analysis else []
            failure_by_ref = {failure.span_ref: failure for failure in failures}
            for span in traces.spans:
                failure = failure_by_ref.get(span.evidence_ref)
                trace_claims[span.evidence_ref] = {
                    "service": span.service,
                    "dependency": failure.dependency if failure else span.peer_service,
                    "failure_type": failure.failure_type if failure else None,
                }
                trace_facts.append(
                    {
                        "ref": span.evidence_ref,
                        "service": span.service,
                        "dependency": trace_claims[span.evidence_ref]["dependency"],
                        "failure_type": trace_claims[span.evidence_ref]["failure_type"],
                        "status": span.status,
                    }
                )
        strengths = {ref: "weak" for ref in [*log_refs, *trace_claims]}
        for edge in graph.edges:
            if edge.edge_type == "SPAN_CORROBORATED_BY_LOG" and edge.correlation_level in {
                "strong",
                "medium",
            }:
                strengths[edge.from_ref] = edge.correlation_level
                signal = next((node for node in graph.nodes if node.node_id == edge.to_ref), None)
                if signal and log_analysis:
                    for candidate in log_analysis.signals:
                        if candidate.signal_id == signal.node_id:
                            for ref in candidate.sample_refs:
                                strengths[ref] = edge.correlation_level
        allowed_refs = [*[fact["ref"] for fact in exec_facts], *log_refs, *sorted(trace_claims)]
        context = FailureTriageContext(
            prompt_payload={
                "execution_facts": exec_facts,
                "log_analysis": log_facts,
                "trace_analysis": trace_facts,
                "root_cause_graph": graph.model_dump(mode="json"),
                "allowed_evidence_refs": allowed_refs,
            },
            allowed_evidence_refs=allowed_refs,
            log_services=log_services,
            log_exceptions=log_exceptions,
            trace_claims=trace_claims,
            evidence_strength=strengths,
        )
        engine = getattr(self, "_engine", None) or FailureTriageEngine(self._model)
        engine_result = engine.triage(context)
        create_only_json(
            root / "triage-generation.json",
            {
                "schema_version": "agentic-qa.triage-generation.v1",
                "attempts": engine_result.attempts,
                "input_sha256": engine_result.input_sha256,
            },
        )
        identity = log_analysis or trace_analysis
        triage = self._build(
            engine_result.proposal,
            engine_result.issues,
            identity,
            hashlib.sha256(execution_bytes).hexdigest(),
            hashlib.sha256(log_bytes).hexdigest() if log_bytes else None,
            hashlib.sha256(analysis_bytes).hexdigest() if analysis_bytes else None,
            hashlib.sha256(trace_bytes).hexdigest() if trace_bytes else None,
            hashlib.sha256(trace_analysis_bytes).hexdigest() if trace_analysis_bytes else None,
            hashlib.sha256(graph_bytes).hexdigest(),
            allowed_refs,
        )
        create_only_json(target, triage.model_dump(mode="json"))
        return item.model_copy(
            update={
                "triage_status": triage.triage_status,
                "failure_triage_path": target.relative_to(workspace_root).as_posix(),
            }
        )

    @staticmethod
    def _optional_logs(root):
        evidence = root / "log-evidence.json"
        analysis = root / "log-analysis.json"
        if not evidence.is_file() or not analysis.is_file():
            return None, None, None, None
        evidence_bytes = evidence.read_bytes()
        analysis_bytes = analysis.read_bytes()
        return (
            LogEvidenceBundle.model_validate_json(evidence_bytes),
            LogAnalysis.model_validate_json(analysis_bytes),
            evidence_bytes,
            analysis_bytes,
        )

    @staticmethod
    def _optional_traces(root):
        evidence = root / "trace-evidence.json"
        analysis = root / "trace-analysis.json"
        if not evidence.is_file() or not analysis.is_file():
            return None, None, None, None
        evidence_bytes = evidence.read_bytes()
        analysis_bytes = analysis.read_bytes()
        return (
            TraceEvidenceBundle.model_validate_json(evidence_bytes),
            TraceAnalysis.model_validate_json(analysis_bytes),
            evidence_bytes,
            analysis_bytes,
        )

    @staticmethod
    def _build(
        proposal,
        issues,
        identity,
        execution_sha,
        logs_sha,
        log_analysis_sha,
        trace_sha,
        trace_analysis_sha,
        graph_sha,
        allowed_refs,
    ) -> FailureTriageV2:
        if proposal is None:
            status = "failed"
            likelihood = "insufficient_evidence"
            primary = None
            alternatives: list[FailureHypothesis] = []
            actions = ["Human review required: " + "; ".join(issues)]
        else:
            primary = proposal.primary
            likelihood = (
                "highly_likely"
                if primary.confidence >= 0.9 and primary.evidence_refs
                else "probable"
                if primary.confidence >= 0.7 and primary.evidence_refs
                else "insufficient_evidence"
            )
            status = "insufficient_evidence" if likelihood == "insufficient_evidence" else "success"
            alternatives = proposal.alternatives
            actions = proposal.recommended_actions
        values = {
            "collection_id": identity.collection_id,
            "execution_id": identity.execution_id,
            "case_id": identity.case_id,
            "dataset_id": identity.dataset_id,
            "execution_evidence_sha256": execution_sha,
            "log_evidence_sha256": logs_sha,
            "log_analysis_sha256": log_analysis_sha,
            "trace_evidence_sha256": trace_sha,
            "trace_analysis_sha256": trace_analysis_sha,
            "root_cause_graph_sha256": graph_sha,
            "triage_status": status,
            "likelihood": likelihood,
            "primary": primary,
            "alternatives": alternatives,
            "recommended_actions": actions,
            "available_evidence_refs": allowed_refs,
        }
        payload = FailureTriageV2.model_construct(**values, content_sha256="0" * 64).model_dump(
            mode="json", exclude={"content_sha256"}
        )
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return FailureTriageV2.model_validate({**payload, "content_sha256": digest})

    @staticmethod
    def _validate_linked_hashes(root, triage, workspace_root, execution_id):
        expected = {
            workspace_root
            / "executions"
            / execution_id
            / "evidence.json": triage.execution_evidence_sha256,
            root / "log-evidence.json": triage.log_evidence_sha256,
            root / "log-analysis.json": triage.log_analysis_sha256,
            root / "trace-evidence.json": triage.trace_evidence_sha256,
            root / "trace-analysis.json": triage.trace_analysis_sha256,
            root / "root-cause-graph.json": triage.root_cause_graph_sha256,
        }
        for path, digest in expected.items():
            if digest and (
                not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest
            ):
                raise ValueError("failure triage source hash does not match")
