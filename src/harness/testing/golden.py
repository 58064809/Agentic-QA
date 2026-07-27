from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from harness.application.qa_design import (
    parse_requirement_markdown,
    parse_testcase_markdown,
    render_requirement_catalog,
)
from harness.domain.models import StrictModel
from harness.domain.schemas.qa_design import (
    RequirementCatalog,
    TestCaseSet,
    validate_testcase_set,
)


class GoldenExpectation(StrictModel):
    schema_version: str = "agentic-qa.golden-expectation.v1"
    must_extract_rules: list[str] = Field(min_length=1)
    must_cover_points: list[str] = Field(min_length=1)
    forbidden_inventions: list[str] = Field(default_factory=list)
    minimum_score: float = Field(ge=0, le=1)


def evaluate_golden_case(case_root: Path) -> dict[str, Any]:
    candidate_catalog = RequirementCatalog.model_validate_json(
        (case_root / "candidate-requirement-catalog.json").read_text(encoding="utf-8")
    )
    return evaluate_candidate_artifacts(
        case_root,
        requirement_content=render_requirement_catalog(candidate_catalog),
        testcase_content=(case_root / "candidate-testcases.md").read_text(encoding="utf-8"),
        artifact_names={
            "requirement_catalog": "candidate-requirement-catalog.json",
            "testcases": "candidate-testcases.md",
        },
    )


def evaluate_candidate_artifacts(
    case_root: Path,
    *,
    requirement_content: str,
    testcase_content: str,
    artifact_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    source = (case_root / "source.md").read_text(encoding="utf-8")
    expected_catalog = RequirementCatalog.model_validate_json(
        (case_root / "expectations.json").read_text(encoding="utf-8")
    )
    expected = GoldenExpectation.model_validate_json(
        (case_root / "thresholds.json").read_text(encoding="utf-8")
    )
    baseline = TestCaseSet.model_validate_json(
        (case_root / "baseline-testcases.json").read_text(encoding="utf-8")
    )
    candidate_catalog = parse_requirement_markdown(requirement_content)
    candidate = parse_testcase_markdown(testcase_content)
    aliases = _rule_aliases(expected_catalog, candidate_catalog)
    normalized_candidate = _alias_testcase_rules(candidate, aliases)
    normalized_catalog = _alias_catalog_rules(candidate_catalog, aliases)
    issues = [
        issue
        for issue in validate_testcase_set(normalized_catalog, normalized_candidate)
        if issue.code not in {"boundary_value_uncovered", "state_transition_uncovered"}
    ]

    candidate_rules = {aliases.get(rule.rule_id, rule.rule_id) for rule in candidate_catalog.rules}
    mapped_rules = {aliases.get(mapping.rule_id, mapping.rule_id) for mapping in candidate.coverage}
    extracted = set(expected.must_extract_rules) & candidate_rules
    covered_points = _covered_points(normalized_candidate, testcase_content, expected_catalog)
    covered = set(expected.must_cover_points) & covered_points
    rendered_candidate = (requirement_content + "\n" + testcase_content).casefold()
    invented = [
        item
        for item in expected.forbidden_inventions
        if item.casefold() in rendered_candidate and item.casefold() not in source.casefold()
    ]
    duplicate_count = sum(issue.code == "duplicate_testcase" for issue in issues)
    executable_count = sum(
        bool(case.steps and case.expected_results and case.assertions)
        for case in normalized_candidate.cases
    )

    rule_recall = len(extracted) / len(expected.must_extract_rules)
    coverage_rate = len(covered) / len(expected.must_cover_points)
    hallucination_rate = len(invented) / max(len(expected.forbidden_inventions), 1)
    duplicate_rate = duplicate_count / len(normalized_candidate.cases)
    executable_rate = executable_count / len(normalized_candidate.cases)
    semantic_issue_rate = len(issues) / max(
        len(expected.must_extract_rules) + len(expected.must_cover_points), 1
    )
    score = _score(
        rule_recall=rule_recall,
        coverage_rate=coverage_rate,
        executable_rate=executable_rate,
        hallucination_rate=hallucination_rate,
        duplicate_rate=duplicate_rate,
        semantic_issue_rate=semantic_issue_rate,
    )
    baseline_score = _baseline_score(expected_catalog, expected, baseline, source)
    return {
        "case": case_root.name,
        "passed": score >= expected.minimum_score and not issues and not invented,
        "score": round(score, 4),
        "baseline_score": round(baseline_score, 4),
        "baseline_gap": round(score - baseline_score, 4),
        "minimum_score": expected.minimum_score,
        "metrics": {
            "rule_recall": round(rule_recall, 4),
            "coverage_rate": round(coverage_rate, 4),
            "hallucination_rate": round(hallucination_rate, 4),
            "duplicate_rate": round(duplicate_rate, 4),
            "executable_rate": round(executable_rate, 4),
        },
        "missing_rules": sorted(set(expected.must_extract_rules) - candidate_rules),
        "missing_coverage": sorted(set(expected.must_cover_points) - covered_points),
        "invented_terms": invented,
        "validation_issues": [issue.model_dump(mode="json") for issue in issues],
        "mapped_rule_count": len(mapped_rules),
        "candidate_artifacts": artifact_names
        or {
            "requirement_catalog": "generated requirement_analysis/raw.md",
            "testcases": "generated testcases/raw.md",
        },
    }


def run_golden_eval(root: Path | None = None) -> dict[str, Any]:
    source_tree_root = Path(__file__).resolve().parents[3] / "evals" / "cases"
    working_tree_root = Path.cwd() / "evals" / "cases"
    cases_root = root or (working_tree_root if working_tree_root.is_dir() else source_tree_root)
    if not cases_root.is_dir():
        raise FileNotFoundError("golden eval cases are unavailable; run from the repository root")
    case_results = [
        evaluate_golden_case(path) for path in sorted(cases_root.iterdir()) if path.is_dir()
    ]
    return {
        "schema_version": "agentic-qa.harness.golden-eval-result.v1",
        "passed": bool(case_results) and all(result["passed"] for result in case_results),
        "case_count": len(case_results),
        "cases": case_results,
    }


def _covered_points(
    testcase_set: TestCaseSet,
    rendered: str,
    expected_catalog: RequirementCatalog,
) -> set[str]:
    points = {mapping.rule_id for mapping in testcase_set.coverage}
    folded = rendered.casefold()
    for case in testcase_set.cases:
        points.add(f"type:{case.test_type}")
    for rule in expected_catalog.rules:
        for boundary in rule.boundaries:
            points.update(
                f"boundary:{value}" for value in boundary.values if value.casefold() in folded
            )
        for transition in rule.state_transitions:
            if all(
                value.casefold() in folded
                for value in (
                    transition.from_state,
                    transition.event,
                    transition.to_state,
                )
            ):
                points.add(
                    f"transition:{transition.from_state}->{transition.event}->{transition.to_state}"
                )
    return points


def _rule_aliases(
    expected: RequirementCatalog,
    candidate: RequirementCatalog,
) -> dict[str, str]:
    expected_ids = [rule.rule_id for rule in expected.rules]
    candidate_ids = [rule.rule_id for rule in candidate.rules]
    aliases = {rule_id: rule_id for rule_id in set(expected_ids) & set(candidate_ids)}
    unmatched_expected = [rule_id for rule_id in expected_ids if rule_id not in aliases]
    unmatched_candidate = [rule_id for rule_id in candidate_ids if rule_id not in aliases]
    if len(unmatched_expected) == len(unmatched_candidate):
        aliases.update(zip(unmatched_candidate, unmatched_expected, strict=True))
    return aliases


def _alias_testcase_rules(
    testcase_set: TestCaseSet,
    aliases: dict[str, str],
) -> TestCaseSet:
    return testcase_set.model_copy(
        update={
            "cases": [
                case.model_copy(
                    update={
                        "rule_ids": [aliases.get(rule_id, rule_id) for rule_id in case.rule_ids]
                    }
                )
                for case in testcase_set.cases
            ],
            "coverage": [
                mapping.model_copy(
                    update={"rule_id": aliases.get(mapping.rule_id, mapping.rule_id)}
                )
                for mapping in testcase_set.coverage
            ],
        }
    )


def _alias_catalog_rules(
    catalog: RequirementCatalog,
    aliases: dict[str, str],
) -> RequirementCatalog:
    return catalog.model_copy(
        update={
            "rules": [
                rule.model_copy(
                    update={
                        "rule_id": aliases.get(rule.rule_id, rule.rule_id),
                        "conflicts_with": [
                            aliases.get(rule_id, rule_id) for rule_id in rule.conflicts_with
                        ],
                    }
                )
                for rule in catalog.rules
            ]
        }
    )


def _score(
    *,
    rule_recall: float,
    coverage_rate: float,
    executable_rate: float,
    hallucination_rate: float,
    duplicate_rate: float,
    semantic_issue_rate: float,
) -> float:
    return max(
        0.0,
        (
            0.30 * rule_recall
            + 0.35 * coverage_rate
            + 0.20 * executable_rate
            + 0.15 * (1 - hallucination_rate)
            - 0.20 * duplicate_rate
            - 0.20 * semantic_issue_rate
        ),
    )


def _baseline_score(
    catalog: RequirementCatalog,
    expected: GoldenExpectation,
    baseline: TestCaseSet,
    source: str,
) -> float:
    issues = validate_testcase_set(catalog, baseline)
    points = {mapping.rule_id for mapping in baseline.coverage}
    for case in baseline.cases:
        points.update(f"boundary:{value}" for value in case.covered_boundary_values)
        points.update(
            f"transition:{item.from_state}->{item.event}->{item.to_state}"
            for item in case.covered_transitions
        )
        points.add(f"type:{case.test_type}")
    rendered = baseline.model_dump_json().casefold()
    invented = [
        item
        for item in expected.forbidden_inventions
        if item.casefold() in rendered and item.casefold() not in source.casefold()
    ]
    return _score(
        rule_recall=(
            len(set(expected.must_extract_rules) & {rule.rule_id for rule in catalog.rules})
            / len(expected.must_extract_rules)
        ),
        coverage_rate=len(set(expected.must_cover_points) & points)
        / len(expected.must_cover_points),
        executable_rate=(
            sum(
                bool(case.steps and case.expected_results and case.assertions)
                for case in baseline.cases
            )
            / len(baseline.cases)
        ),
        hallucination_rate=len(invented) / max(len(expected.forbidden_inventions), 1),
        duplicate_rate=(
            sum(issue.code == "duplicate_testcase" for issue in issues) / len(baseline.cases)
        ),
        semantic_issue_rate=len(issues)
        / max(len(expected.must_extract_rules) + len(expected.must_cover_points), 1),
    )
