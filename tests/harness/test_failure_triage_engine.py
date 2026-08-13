from __future__ import annotations

from harness.application.failure_triage_engine import (
    SYSTEM,
    FailureTriageContext,
    FailureTriageEngine,
)
from harness.domain.schemas.failure_triage import FailureTriageProposal


class _Model:
    def __init__(self, proposals):
        self.proposals = list(proposals)
        self.calls = 0

    def structured(self, **_kwargs):
        value = self.proposals[self.calls]
        self.calls += 1
        return FailureTriageProposal.model_validate(value)


def test_engine_system_prompt_declares_json_output_protocol() -> None:
    assert "json" in SYSTEM.casefold()
    assert '"primary"' in SYSTEM
    assert '"evidence_refs"' in SYSTEM


def _proposal(**updates):
    primary = {
        "category": "dependency",
        "service": "inventory-service",
        "dependency": "mysql",
        "failure_type": "timeout",
        "summary": "inventory-service mysql timeout",
        "confidence": 0.99,
        "evidence_refs": ["TRACE-000001"],
    }
    primary.update(updates)
    return {"primary": primary, "alternatives": [], "recommended_actions": []}


def _context(strength="weak"):
    return FailureTriageContext(
        prompt_payload={"facts": []},
        allowed_evidence_refs=["TRACE-000001", "LOG-000001"],
        log_services={"inventory-service"},
        log_exceptions={"SQLTimeoutException"},
        trace_claims={
            "TRACE-000001": {
                "service": "inventory-service",
                "dependency": "mysql",
                "failure_type": "timeout",
            }
        },
        evidence_strength={"TRACE-000001": strength, "LOG-000001": strength},
    )


def test_engine_revises_unsupported_trace_claim_and_caps_confidence() -> None:
    model = _Model([_proposal(dependency="redis"), _proposal()])
    result = FailureTriageEngine(model).triage(_context("weak"))
    assert model.calls == 2
    assert result.proposal is not None
    assert result.proposal.primary.confidence == 0.89
    assert result.proposal.primary.evidence_strength == "weak"
    assert "unsupported dependency: redis" in result.attempts[0]["issues"]


def test_engine_requires_log_ref_for_exception_claim() -> None:
    proposal = _proposal(
        exception_type="SQLTimeoutException",
        summary="SQLTimeoutException caused the timeout",
    )
    result = FailureTriageEngine(_Model([proposal, proposal])).triage(_context())
    assert result.proposal is None
    assert "unsupported exception: SQLTimeoutException" in result.issues


def test_engine_accepts_mixed_trace_and_log_evidence_as_strong() -> None:
    proposal = _proposal(
        exception_type="SQLTimeoutException",
        summary="SQLTimeoutException caused the timeout",
        evidence_refs=["TRACE-000001", "LOG-000001"],
    )
    result = FailureTriageEngine(_Model([proposal])).triage(_context("strong"))
    assert result.proposal is not None
    assert result.proposal.primary.confidence == 0.99
    assert result.proposal.primary.evidence_strength == "strong"
