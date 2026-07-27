from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from harness.domain.models import StrictModel

RULE_ID_PATTERN = r"^[A-Z][A-Z0-9_-]*-\d{3,}$"
TESTCASE_ID_PATTERN = r"^TC-[A-Z0-9_-]*\d{3,}$"
VAGUE_ASSERTION_PATTERN = re.compile(
    r"^(?:正常|成功|符合预期|结果正确|功能正常|无异常|通过)[。.!！]?$"
)


class EvidenceLevel(str, Enum):
    CONFIRMED = "confirmed"
    INFERRED = "inferred"
    UNCONFIRMED = "unconfirmed"


class SourceReference(StrictModel):
    source: str = Field(min_length=1)
    section: str | None = None
    quote_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    chunk_id: str | None = None
    selection_reason: str | None = None


class BoundaryRequirement(StrictModel):
    field: str = Field(min_length=1)
    values: list[str] = Field(min_length=1)

    @field_validator("values")
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("boundary values cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("boundary values cannot contain duplicates")
        return normalized


class StateTransition(StrictModel):
    from_state: str = Field(min_length=1)
    event: str = Field(min_length=1)
    to_state: str = Field(min_length=1)


class RequirementRule(StrictModel):
    rule_id: str = Field(pattern=RULE_ID_PATTERN)
    title: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    evidence_level: EvidenceLevel
    source_refs: list[SourceReference] = Field(default_factory=list)
    boundaries: list[BoundaryRequirement] = Field(default_factory=list)
    state_transitions: list[StateTransition] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_evidence_for_confirmed_rule(self) -> RequirementRule:
        if self.evidence_level == EvidenceLevel.CONFIRMED and not self.source_refs:
            raise ValueError(f"confirmed rule {self.rule_id} requires source_refs")
        return self


class RequirementCatalog(StrictModel):
    schema_version: Literal["agentic-qa.requirement-catalog.v1"] = (
        "agentic-qa.requirement-catalog.v1"
    )
    sources: list[SourceReference] = Field(default_factory=list)
    actors: list[str] = Field(default_factory=list)
    business_objects: list[str] = Field(default_factory=list)
    flows: list[str] = Field(default_factory=list)
    rules: list[RequirementRule] = Field(default_factory=list)
    forbidden_inventions: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_catalog(self) -> RequirementCatalog:
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("requirement rule IDs must be unique")
        known = set(rule_ids)
        for rule in self.rules:
            unknown = (set(rule.conflicts_with) - known) | (
                {rule.rule_id} if rule.rule_id in rule.conflicts_with else set()
            )
            if unknown:
                raise ValueError(
                    f"rule {rule.rule_id} has invalid conflicts_with references: {sorted(unknown)}"
                )
        return self

    @property
    def confirmed_rule_ids(self) -> set[str]:
        return {
            rule.rule_id for rule in self.rules if rule.evidence_level == EvidenceLevel.CONFIRMED
        }


class RiskLevel(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class RiskItem(StrictModel):
    risk_id: str = Field(pattern=r"^RISK-\d{3,}$")
    title: str = Field(min_length=1)
    rule_ids: list[str] = Field(min_length=1)
    priority: RiskLevel
    rationale: str = Field(min_length=1)
    coverage_intent: list[str] = Field(min_length=1)


class RiskCatalog(StrictModel):
    schema_version: Literal["agentic-qa.risk-catalog.v1"] = "agentic-qa.risk-catalog.v1"
    risks: list[RiskItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_risks(self) -> RiskCatalog:
        ids = [risk.risk_id for risk in self.risks]
        if len(ids) != len(set(ids)):
            raise ValueError("risk IDs must be unique")
        return self


class TestCase(StrictModel):
    case_id: str = Field(pattern=TESTCASE_ID_PATTERN)
    rule_ids: list[str] = Field(min_length=1, max_length=3)
    title: str = Field(min_length=1)
    test_type: str = Field(min_length=1)
    priority: RiskLevel
    preconditions: list[str] = Field(min_length=1)
    test_data: list[str] = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    expected_results: list[str] = Field(min_length=1)
    assertions: list[str] = Field(min_length=1)
    pending_items: list[str] = Field(default_factory=list)
    covered_boundary_values: list[str] = Field(default_factory=list)
    covered_transitions: list[StateTransition] = Field(default_factory=list)

    @field_validator(
        "rule_ids",
        "preconditions",
        "test_data",
        "steps",
        "expected_results",
        "assertions",
        "pending_items",
        "covered_boundary_values",
    )
    @classmethod
    def normalize_string_lists(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("test case list values cannot be empty")
        return normalized

    @model_validator(mode="after")
    def reject_vague_or_non_atomic_case(self) -> TestCase:
        if len(self.rule_ids) != len(set(self.rule_ids)):
            raise ValueError(f"{self.case_id} rule_ids must be unique")
        vague = [
            value
            for value in [*self.expected_results, *self.assertions]
            if VAGUE_ASSERTION_PATTERN.fullmatch(value.strip())
        ]
        if vague:
            raise ValueError(f"{self.case_id} contains vague expected result/assertion: {vague}")
        if all(len(step) < 4 for step in self.steps):
            raise ValueError(f"{self.case_id} steps are not executable")
        return self


class CoverageMapping(StrictModel):
    rule_id: str = Field(pattern=RULE_ID_PATTERN)
    case_ids: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)

    @field_validator("case_ids")
    @classmethod
    def unique_case_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("coverage case_ids must be unique")
        return values


class TestCaseSet(StrictModel):
    schema_version: Literal["agentic-qa.test-case-set.v1"] = "agentic-qa.test-case-set.v1"
    requirement_catalog_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    cases: list[TestCase] = Field(min_length=1)
    coverage: list[CoverageMapping] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_internal_references(self) -> TestCaseSet:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("test case IDs must be unique")
        known_cases = set(case_ids)
        coverage_rules: set[str] = set()
        for mapping in self.coverage:
            missing = set(mapping.case_ids) - known_cases
            if missing:
                raise ValueError(
                    f"coverage for {mapping.rule_id} references missing cases: {sorted(missing)}"
                )
            if mapping.rule_id in coverage_rules:
                raise ValueError(f"coverage rule {mapping.rule_id} is duplicated")
            coverage_rules.add(mapping.rule_id)
            for case_id in mapping.case_ids:
                case = next(item for item in self.cases if item.case_id == case_id)
                if mapping.rule_id not in case.rule_ids:
                    raise ValueError(
                        f"coverage {mapping.rule_id} references {case_id}, "
                        "but the case does not declare that rule"
                    )
        return self


class TestCasePatch(StrictModel):
    schema_version: Literal["agentic-qa.test-case-patch.v1"] = "agentic-qa.test-case-patch.v1"
    replace_cases: list[TestCase] = Field(default_factory=list)
    remove_case_ids: list[str] = Field(default_factory=list)
    replace_coverage: list[CoverageMapping] = Field(default_factory=list)


class DesignValidationIssue(StrictModel):
    code: str
    message: str
    rule_id: str | None = None
    case_id: str | None = None


def validate_testcase_set(
    catalog: RequirementCatalog,
    testcase_set: TestCaseSet,
) -> tuple[DesignValidationIssue, ...]:
    issues: list[DesignValidationIssue] = []
    known_rules = {rule.rule_id: rule for rule in catalog.rules}
    case_by_id = {case.case_id: case for case in testcase_set.cases}
    mapped_rules = {mapping.rule_id for mapping in testcase_set.coverage}

    for case in testcase_set.cases:
        for rule_id in case.rule_ids:
            if rule_id not in known_rules:
                issues.append(
                    DesignValidationIssue(
                        code="unknown_rule_reference",
                        message=f"{case.case_id} references unknown rule {rule_id}",
                        rule_id=rule_id,
                        case_id=case.case_id,
                    )
                )

    for rule_id in sorted(catalog.confirmed_rule_ids - mapped_rules):
        issues.append(
            DesignValidationIssue(
                code="confirmed_rule_uncovered",
                message=f"confirmed rule {rule_id} has no coverage mapping",
                rule_id=rule_id,
            )
        )

    for rule in catalog.rules:
        covered_cases = [case for case in testcase_set.cases if rule.rule_id in case.rule_ids]
        covered_values = {value for case in covered_cases for value in case.covered_boundary_values}
        for boundary in rule.boundaries:
            for value in boundary.values:
                if value not in covered_values:
                    issues.append(
                        DesignValidationIssue(
                            code="boundary_value_uncovered",
                            message=(
                                f"{rule.rule_id} boundary {boundary.field}={value} is not covered"
                            ),
                            rule_id=rule.rule_id,
                        )
                    )
        covered_transitions = {
            (transition.from_state, transition.event, transition.to_state)
            for case in covered_cases
            for transition in case.covered_transitions
        }
        for transition in rule.state_transitions:
            identity = (transition.from_state, transition.event, transition.to_state)
            if identity not in covered_transitions:
                issues.append(
                    DesignValidationIssue(
                        code="state_transition_uncovered",
                        message=(
                            f"{rule.rule_id} transition "
                            f"{transition.from_state} --{transition.event}--> "
                            f"{transition.to_state} is not covered"
                        ),
                        rule_id=rule.rule_id,
                    )
                )

    signatures: dict[tuple[tuple[str, ...], str, tuple[str, ...]], str] = {}
    for case in testcase_set.cases:
        signature = (
            tuple(sorted(case.rule_ids)),
            re.sub(r"\s+", "", case.title).casefold(),
            tuple(re.sub(r"\s+", "", step).casefold() for step in case.steps),
        )
        duplicate = signatures.get(signature)
        if duplicate:
            issues.append(
                DesignValidationIssue(
                    code="duplicate_testcase",
                    message=f"{case.case_id} duplicates {duplicate}",
                    case_id=case.case_id,
                )
            )
        signatures[signature] = case.case_id

    source_corpus = "\n".join(
        reference.source + " " + (reference.section or "") for reference in catalog.sources
    )
    forbidden = [item.casefold() for item in catalog.forbidden_inventions]
    for case in testcase_set.cases:
        rendered = " ".join(
            [
                case.title,
                *case.preconditions,
                *case.test_data,
                *case.steps,
                *case.expected_results,
                *case.assertions,
            ]
        ).casefold()
        for term in forbidden:
            if term and term in rendered and term not in source_corpus.casefold():
                issues.append(
                    DesignValidationIssue(
                        code="forbidden_invention",
                        message=f"{case.case_id} contains forbidden invention: {term}",
                        case_id=case.case_id,
                    )
                )

    for mapping in testcase_set.coverage:
        if mapping.rule_id not in known_rules:
            issues.append(
                DesignValidationIssue(
                    code="coverage_unknown_rule",
                    message=f"coverage references unknown rule {mapping.rule_id}",
                    rule_id=mapping.rule_id,
                )
            )
        for case_id in mapping.case_ids:
            if case_id not in case_by_id:
                issues.append(
                    DesignValidationIssue(
                        code="coverage_missing_case",
                        message=f"coverage references missing case {case_id}",
                        rule_id=mapping.rule_id,
                        case_id=case_id,
                    )
                )
    return tuple(issues)


def apply_testcase_patch(current: TestCaseSet, patch: TestCasePatch) -> TestCaseSet:
    removed = set(patch.remove_case_ids)
    replacements = {case.case_id: case for case in patch.replace_cases}
    cases = [
        replacements.pop(case.case_id, case)
        for case in current.cases
        if case.case_id not in removed
    ]
    cases.extend(replacements.values())
    coverage_replacements = {item.rule_id: item for item in patch.replace_coverage}
    coverage = [
        coverage_replacements.pop(item.rule_id, item)
        for item in current.coverage
        if all(case_id not in removed for case_id in item.case_ids)
    ]
    coverage.extend(coverage_replacements.values())
    return current.model_copy(update={"cases": cases, "coverage": coverage})
