from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import Field

from harness.application.model_port import ModelGateway, ModelRoute
from harness.domain.models import StrictModel
from harness.domain.schemas.failure_triage import FailureHypothesis, FailureTriageProposal

SYSTEM = """You are the failure_triager. Analyze only the supplied redacted facts.
Return one JSON structured hypothesis with citations. Never claim a service, dependency, exception,
or fact not present in the indexed context. Automated analysis is never confirmed. Do not request
logs, traces, credentials, tools, LogQL, TraceQL, files, or network access."""
EXCEPTION_CLAIM = re.compile(r"\b[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?:Exception|Error)\b")
CONFIDENCE_CAP = {"strong": 1.0, "medium": 0.94, "weak": 0.89}


class FailureTriageContext(StrictModel):
    prompt_payload: dict[str, Any]
    allowed_evidence_refs: list[str]
    log_services: set[str] = Field(default_factory=set)
    log_exceptions: set[str] = Field(default_factory=set)
    trace_claims: dict[str, dict[str, str | None]] = Field(default_factory=dict)
    evidence_strength: dict[str, str] = Field(default_factory=dict)


class FailureTriageEngineResult(StrictModel):
    proposal: FailureTriageProposal | None = None
    issues: list[str] = Field(default_factory=list)
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    input_sha256: str


class FailureTriageEngine:
    def __init__(self, model: ModelGateway) -> None:
        self._model = model

    def triage(self, context: FailureTriageContext) -> FailureTriageEngineResult:
        route = ModelRoute(
            tier="pro",
            thinking="enabled",
            reasoning_effort="high",
            purpose="expert:failure_triager",
        )
        attempts: list[dict[str, Any]] = []
        proposal = None
        issues: list[str] = []
        for attempt in range(2):
            prompt = json.dumps(context.prompt_payload, ensure_ascii=False, sort_keys=True)
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
                issues = self.validate(candidate, context)
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
                    proposal = self._apply_policy(candidate, context)
                    break
            except Exception as exc:
                issues = [f"model_error:{type(exc).__name__}"]
                attempts.append({"attempt": attempt + 1, "issues": issues})
        canonical = json.dumps(
            context.prompt_payload, sort_keys=True, separators=(",", ":")
        ).encode()
        return FailureTriageEngineResult(
            proposal=proposal,
            issues=issues,
            attempts=attempts,
            input_sha256=hashlib.sha256(canonical).hexdigest(),
        )

    @staticmethod
    def validate(proposal: FailureTriageProposal, context: FailureTriageContext) -> list[str]:
        allowed = set(context.allowed_evidence_refs)
        issues: list[str] = []
        for hypothesis in [proposal.primary, *proposal.alternatives]:
            refs = set(hypothesis.evidence_refs)
            trace_refs = sorted(ref for ref in refs if ref.startswith("TRACE-"))
            log_refs = sorted(ref for ref in refs if ref.startswith("LOG-"))
            if not refs or not refs <= allowed:
                issues.append("hypothesis evidence_refs are empty or unresolved")
            supported_trace = [
                context.trace_claims[ref] for ref in trace_refs if ref in context.trace_claims
            ]
            if (
                hypothesis.service
                and hypothesis.service not in context.log_services
                and not any(claim.get("service") == hypothesis.service for claim in supported_trace)
            ):
                issues.append(f"unsupported service: {hypothesis.service}")
            if hypothesis.exception_type and (
                hypothesis.exception_type not in context.log_exceptions or not log_refs
            ):
                issues.append(f"unsupported exception: {hypothesis.exception_type}")
            summary_exceptions = EXCEPTION_CLAIM.findall(hypothesis.summary)
            if any(item not in context.log_exceptions for item in summary_exceptions) or (
                summary_exceptions and not log_refs
            ):
                issues.append("unsupported exception claim in summary")
            if hypothesis.dependency and not any(
                claim.get("dependency") == hypothesis.dependency for claim in supported_trace
            ):
                issues.append(f"unsupported dependency: {hypothesis.dependency}")
            if hypothesis.failure_type and not any(
                claim.get("failure_type") == hypothesis.failure_type for claim in supported_trace
            ):
                issues.append(f"unsupported failure type: {hypothesis.failure_type}")
        return sorted(set(issues))

    @staticmethod
    def _apply_policy(
        proposal: FailureTriageProposal, context: FailureTriageContext
    ) -> FailureTriageProposal:
        def update(hypothesis: FailureHypothesis) -> FailureHypothesis:
            strengths = [
                context.evidence_strength.get(ref, "weak") for ref in hypothesis.evidence_refs
            ]
            strength = (
                "strong" if "strong" in strengths else "medium" if "medium" in strengths else "weak"
            )
            return hypothesis.model_copy(
                update={
                    "confidence": min(hypothesis.confidence, CONFIDENCE_CAP[strength]),
                    "evidence_strength": strength,
                }
            )

        return proposal.model_copy(
            update={
                "primary": update(proposal.primary),
                "alternatives": [update(item) for item in proposal.alternatives],
            }
        )
