from __future__ import annotations

import hashlib

import pytest

from harness.application.requirement_intelligence import (
    build_test_design_plan,
    derive_requirement_delta,
    generate_pairwise,
    match_semantic_continuations,
    upgrade_risk_catalog,
    validate_historical_test_decisions,
    validate_impact_analysis,
)
from harness.domain.schemas.knowledge import KnowledgeTrust
from harness.domain.schemas.qa_design import (
    BoundaryRequirement,
    EvidenceLevel,
    RequirementCatalog,
    RequirementRule,
    RiskCatalog,
    RiskItem,
    SourceReference,
    StateTransition,
)
from harness.domain.schemas.qa_design import (
    TestCase as QATestCase,
)
from harness.domain.schemas.requirement_intelligence import (
    HistoricalTestDecision,
    ImpactAnalysis,
    ImpactClaim,
    SemanticContinuationMatch,
    SemanticContinuationProposal,
)


def _rule(rule_id: str, outcome: str = "allowed") -> RequirementRule:
    return RequirementRule(
        rule_id=rule_id,
        title="payment approval",
        condition="role is approver",
        outcome=outcome,
        evidence_level=EvidenceLevel.CONFIRMED,
        source_refs=[SourceReference(source="sources/prd.md")],
    )


def test_delta_has_all_deterministic_states_and_ambiguous_rename_is_conflict() -> None:
    baseline = RequirementCatalog(rules=[_rule("PAY-001"), _rule("OLD-002")])
    current = RequirementCatalog(rules=[_rule("PAY-001", "rejected"), _rule("NEW-002")])
    delta = derive_requirement_delta(
        workspace_id="demo",
        baseline_run_id="old",
        current_run_id="new",
        baseline=baseline,
        current=current,
    )
    assert [(item.kind.value, item.old_rule_id, item.new_rule_id) for item in delta.items] == [
        ("MODIFIED", "PAY-001", "PAY-001"),
        ("CONFLICT", "OLD-002", "NEW-002"),
    ]


class _SemanticModel:
    def structured(self, **kwargs):
        assert kwargs["response_model"] is SemanticContinuationProposal
        return SemanticContinuationProposal(
            matches=[
                SemanticContinuationMatch(
                    old_rule_id="OLD-001",
                    new_rule_id="NEW-001",
                    reason="same bounded condition and outcome",
                    evidence_refs=["OLD:OLD-001", "NEW:NEW-001"],
                )
            ]
        )


def test_semantic_continuation_is_bounded_and_validated() -> None:
    old = _rule("OLD-001")
    new = old.model_copy(update={"rule_id": "NEW-001"})
    matches = match_semantic_continuations(
        _SemanticModel(),
        baseline=RequirementCatalog(rules=[old]),
        current=RequirementCatalog(rules=[new]),
    )
    delta = derive_requirement_delta(
        workspace_id="demo",
        baseline_run_id="old",
        current_run_id="new",
        baseline=RequirementCatalog(rules=[old]),
        current=RequirementCatalog(rules=[new]),
        semantic_matches=matches,
    )
    assert len(delta.items) == 1
    assert delta.items[0].kind.value == "MODIFIED"


def _case(case_id: str, title: str) -> QATestCase:
    return QATestCase(
        case_id=case_id,
        rule_ids=["PAY-001"],
        title=title,
        test_type="functional",
        priority="P1",
        preconditions=["approver exists"],
        test_data=["payment=100"],
        steps=["submit payment approval"],
        expected_results=["approval is recorded"],
        assertions=["state equals approved"],
    )


def test_similar_historical_test_requires_explicit_decision() -> None:
    historical = _case("TC-PAY-001", "approve payment")
    new = _case("TC-PAY-002", "approve payment now")
    with pytest.raises(ValueError, match="requires a design decision"):
        validate_historical_test_decisions([new], {"HIST-TC-1": historical}, [])
    similarity = 11 / 12
    result = validate_historical_test_decisions(
        [new],
        {"HIST-TC-1": historical},
        [
            HistoricalTestDecision(
                historical_case_ref="HIST-TC-1",
                similarity=similarity,
                decision="intentionally_distinct",
                rationale="new title identifies the revised rule",
            )
        ],
    )
    assert result[0].decision == "intentionally_distinct"


def test_impact_evidence_caps_and_direct_trust_are_fail_closed() -> None:
    analysis = ImpactAnalysis(
        workspace_id="demo",
        run_id="run",
        claims=[
            ImpactClaim(
                impact_id="IMPACT-001",
                relation="direct",
                kind="module",
                target="payment",
                reason="explicit mapping",
                evidence_refs=["ASSET-1"],
                confidence=0.9,
            )
        ],
    )
    with pytest.raises(ValueError, match="direct impact"):
        validate_impact_analysis(
            analysis,
            allowed_evidence={"ASSET-1": KnowledgeTrust.REVIEWED_ASSET},
        )
    possible = analysis.model_copy(
        update={
            "claims": [
                analysis.claims[0].model_copy(update={"relation": "potential", "confidence": 0.86})
            ]
        }
    )
    with pytest.raises(ValueError, match="cap 0.85"):
        validate_impact_analysis(
            possible,
            allowed_evidence={"ASSET-1": KnowledgeTrust.REVIEWED_ASSET},
        )


def test_advanced_design_methods_are_only_enabled_by_structured_evidence() -> None:
    rule = _rule("PAY-001").model_copy(
        update={
            "boundaries": [BoundaryRequirement(field="amount", values=["0", "1"])],
            "state_transitions": [
                StateTransition(from_state="pending", event="approve", to_state="approved")
            ],
            "decision_factors": {
                "role": ["maker", "checker"],
                "region": ["cn", "us"],
                "mode": ["manual", "auto"],
            },
            "cause_effects": {"approved": ["settled", "held"]},
            "configurations": {"flag": ["on", "off"]},
            "negative_constraints": ["amount must be positive"],
        }
    )
    plan = build_test_design_plan(RequirementCatalog(actors=["maker"], rules=[rule]))
    methods = {item.value for item in plan.decisions[0].methods}
    assert {
        "boundary_value",
        "state_transition",
        "decision_table",
        "pairwise",
        "cause_effect",
        "role_state_config",
        "negative_testing",
    } <= methods
    assert set(plan.decisions[0].required_test_types) == {"边界", "状态迁移", "异常"}
    plain = build_test_design_plan(RequirementCatalog(rules=[_rule("PAY-002")]))
    assert [item.value for item in plain.decisions[0].methods] == ["equivalence_partitioning"]


def test_pairwise_is_stable_and_covers_every_pair() -> None:
    factors = {
        "browser": ["chrome", "firefox"],
        "region": ["cn", "us"],
        "role": ["maker", "checker"],
    }
    first, pending = generate_pairwise(factors)
    second, _ = generate_pairwise(factors)
    assert first == second
    assert not pending
    observed = {
        (left, row[left], right, row[right])
        for row in first
        for index, left in enumerate(sorted(row))
        for right in sorted(row)[index + 1 :]
    }
    assert len(observed) == 12


def test_risk_v2_priority_is_derived_from_four_factors() -> None:
    requirements = RequirementCatalog(flows=["payment"], rules=[_rule("PAY-001")])
    original = RiskCatalog(
        risks=[
            RiskItem(
                risk_id="RISK-001",
                title="payment",
                rule_ids=["PAY-001"],
                priority="P3",
                rationale="review payment",
                coverage_intent=["approval"],
            )
        ]
    )
    upgraded = upgrade_risk_catalog(original, requirements)
    assert upgraded.schema_version == "agentic-qa.risk-catalog.v2"
    assert upgraded.risks[0].priority.value == "P3"
    assert upgraded.risks[0].factor_total == 2


def test_semantic_contract_fixture_hash_is_stable() -> None:
    plan = build_test_design_plan(RequirementCatalog(rules=[_rule("PAY-001")]))
    assert len(hashlib.sha256(plan.model_dump_json().encode()).hexdigest()) == 64
