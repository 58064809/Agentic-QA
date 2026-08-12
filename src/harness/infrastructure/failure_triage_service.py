from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from harness.application.model_port import ModelGateway, ModelRoute
from harness.domain.schemas.execution_evidence import load_execution_evidence
from harness.domain.schemas.failure_triage import (
    FailureHypothesis,
    FailureTriageProposal,
    FailureTriageV2,
)
from harness.domain.schemas.log_analysis import (
    AnalyzeFailureCommand,
    AnalyzeFailureResult,
    FailureAnalysisItem,
    LogAnalysis,
)
from harness.domain.schemas.log_evidence import LogEvidenceBundle
from harness.infrastructure.failure_analysis import FilesystemFailureAnalysisService
from harness.infrastructure.failure_logs import FilesystemFailureLogService
from harness.infrastructure.failure_report import FilesystemFailureReportService
from harness.infrastructure.persistence.common import create_only_json
from harness.infrastructure.persistence.filesystem import FilesystemStore

SYSTEM = """You are the failure_triager. Analyze only the supplied redacted facts.
Return one structured hypothesis with citations. Never claim a service, exception, or fact not
present in the indexed context. Automated analysis is never confirmed. Do not request logs,
credentials, tools, LogQL, files, or network access."""


class FilesystemFailureTriageService:
    def __init__(self, store: FilesystemStore, model: ModelGateway, local_config, quality) -> None:
        self._store = store
        self._model = model
        self._analysis = FilesystemFailureAnalysisService(store)
        self._collector = FilesystemFailureLogService(store, local_config)
        self._reports = FilesystemFailureReportService(store, quality)

    def collect(self, command):
        return self._collector.collect(command)

    def prepare_report(self, command):
        return self._reports.prepare(command)

    def analyze(self, command: AnalyzeFailureCommand) -> AnalyzeFailureResult:
        deterministic = self._analysis.analyze(command)
        workspace_root = self._store.require_workspace(command.workspace_id).resolve()
        items = [self._triage_one(item, workspace_root, command) for item in deterministic.analyses]
        return deterministic.model_copy(update={"analyses": items})

    def _triage_one(
        self,
        item: FailureAnalysisItem,
        workspace_root: Path,
        command: AnalyzeFailureCommand,
    ) -> FailureAnalysisItem:
        analysis_path = workspace_root / item.log_analysis_path
        root = analysis_path.parent
        target = root / "failure-triage.json"
        if target.exists():
            triage = FailureTriageV2.model_validate_json(target.read_text(encoding="utf-8"))
            return item.model_copy(
                update={
                    "triage_status": triage.triage_status,
                    "failure_triage_path": target.relative_to(workspace_root).as_posix(),
                }
            )
        analysis_bytes = analysis_path.read_bytes()
        log_evidence_path = root / "log-evidence.json"
        log_evidence_bytes = log_evidence_path.read_bytes()
        analysis = LogAnalysis.model_validate_json(analysis_bytes)
        logs = LogEvidenceBundle.model_validate_json(log_evidence_bytes)
        evidence_path = workspace_root / "executions" / command.execution_id / "evidence.json"
        evidence_bytes = evidence_path.read_bytes()
        execution = load_execution_evidence(evidence_bytes)
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
            for signal in analysis.signals
        ]
        allowed_refs = [
            *[item["ref"] for item in exec_facts],
            *sorted({ref for signal in analysis.signals for ref in signal.sample_refs}),
        ]
        prompt_payload = {
            "execution_facts": exec_facts,
            "log_analysis": log_facts,
            "allowed_evidence_refs": allowed_refs,
        }
        route = ModelRoute(
            tier="pro",
            thinking="enabled",
            reasoning_effort="high",
            purpose="expert:failure_triager",
        )
        attempts: list[dict[str, Any]] = []
        proposal: FailureTriageProposal | None = None
        issues: list[str] = []
        for attempt in range(2):
            prompt = json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)
            if issues:
                prompt += "\nREVISION_ISSUES=" + json.dumps(issues, ensure_ascii=False)
            try:
                candidate = self._model.structured(
                    system=SYSTEM,
                    prompt=prompt,
                    response_model=FailureTriageProposal,
                    tools=[],
                    route=route,
                )
                issues = self._validate(candidate, allowed_refs, analysis)
                attempts.append(
                    {
                        "attempt": attempt + 1,
                        "output_sha256": hashlib.sha256(
                            candidate.model_dump_json().encode()
                        ).hexdigest(),
                        "issues": issues,
                    }
                )
                if not issues:
                    proposal = candidate
                    break
            except Exception as exc:
                issues = [f"model_error:{type(exc).__name__}"]
                attempts.append({"attempt": attempt + 1, "issues": issues})
        create_only_json(
            root / "triage-generation.json",
            {
                "schema_version": "agentic-qa.triage-generation.v1",
                "attempts": attempts,
                "input_sha256": hashlib.sha256(
                    json.dumps(prompt_payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            },
        )
        triage = self._build(
            proposal,
            issues,
            analysis,
            logs,
            hashlib.sha256(evidence_bytes).hexdigest(),
            hashlib.sha256(log_evidence_bytes).hexdigest(),
            hashlib.sha256(analysis_bytes).hexdigest(),
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
    def _validate(
        proposal: FailureTriageProposal,
        allowed_refs: list[str],
        analysis: LogAnalysis,
    ) -> list[str]:
        allowed = set(allowed_refs)
        services = {signal.service for signal in analysis.signals}
        exceptions = {signal.exception_type for signal in analysis.signals if signal.exception_type}
        issues: list[str] = []
        for hypothesis in [proposal.primary, *proposal.alternatives]:
            if not hypothesis.evidence_refs or not set(hypothesis.evidence_refs) <= allowed:
                issues.append("hypothesis evidence_refs are empty or unresolved")
            if hypothesis.service and hypothesis.service not in services:
                issues.append(f"unsupported service: {hypothesis.service}")
            if hypothesis.exception_type and hypothesis.exception_type not in exceptions:
                issues.append(f"unsupported exception: {hypothesis.exception_type}")
            if not hypothesis.evidence_refs and hypothesis.confidence >= 0.7:
                issues.append("uncited confidence must be below 0.70")
        return sorted(set(issues))

    @staticmethod
    def _build(
        proposal: FailureTriageProposal | None,
        issues: list[str],
        analysis: LogAnalysis,
        logs: LogEvidenceBundle,
        execution_sha: str,
        logs_sha: str,
        analysis_sha: str,
        allowed_refs: list[str],
    ) -> FailureTriageV2:
        if proposal is None:
            status = "failed"
            likelihood = "insufficient_evidence"
            primary = None
            alternatives: list[FailureHypothesis] = []
            actions = ["Human review required: " + "; ".join(issues)]
        else:
            primary = proposal.primary
            if not primary.evidence_refs and primary.confidence >= 0.7:
                primary = primary.model_copy(update={"confidence": 0.69})
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
        payload = {
            "schema_version": "agentic-qa.failure-triage.v2",
            "collection_id": analysis.collection_id,
            "execution_id": analysis.execution_id,
            "case_id": analysis.case_id,
            "dataset_id": analysis.dataset_id,
            "execution_evidence_sha256": execution_sha,
            "log_evidence_sha256": logs_sha,
            "log_analysis_sha256": analysis_sha,
            "triage_status": status,
            "likelihood": likelihood,
            "primary": primary.model_dump(mode="json") if primary else None,
            "alternatives": [item.model_dump(mode="json") for item in alternatives],
            "recommended_actions": actions,
            "available_evidence_refs": allowed_refs,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return FailureTriageV2.model_validate({**payload, "content_sha256": digest})
