from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, ValidationError

from harness.application.api_contract_validation import validate_api_contracts
from harness.application.model_port import ModelRoute
from harness.application.qa_design import (
    parse_requirement_markdown,
    parse_testcase_markdown,
    render_requirement_catalog,
)
from harness.domain.models import StrictModel
from harness.domain.schemas.api_test_cases import (
    ApiTestCasesDraft,
    load_api_test_cases,
    parse_api_case_variables,
    parse_api_cleanup_steps,
    validate_api_case_runtime_definitions,
    variable_references,
)
from harness.domain.schemas.failure_triage import FailureTriageProposal
from harness.domain.schemas.qa_design import (
    RequirementCatalog,
    RequirementRule,
    TestCaseSet,
    validate_testcase_set,
)
from harness.infrastructure.failure_triage_service import SYSTEM
from harness.infrastructure.log_sanitization import sanitize_log_text
from harness.infrastructure.tools.openapi import inspect_openapi


class GoldenExpectation(StrictModel):
    schema_version: str = "agentic-qa.golden-expectation.v1"
    must_extract_rules: list[str] = Field(min_length=1)
    must_cover_points: list[str] = Field(min_length=1)
    forbidden_inventions: list[str] = Field(default_factory=list)
    minimum_score: float = Field(ge=0, le=1)


class ApiGoldenExpectation(StrictModel):
    schema_version: Literal["agentic-qa.api-golden-expectation.v1"] = (
        "agentic-qa.api-golden-expectation.v1"
    )
    must_cover_points: list[str] = Field(min_length=1)
    minimum_score: float = Field(ge=0, le=1)


class FailureTriageGoldenSignal(StrictModel):
    service: str
    exception_type: str | None = None
    evidence_refs: list[str] = Field(min_length=1)
    raw_message: str
    forbidden_values: list[str] = Field(default_factory=list)
    preserve: list[str] = Field(default_factory=list)


class FailureTriageGoldenCase(StrictModel):
    id: str = Field(pattern=r"^G(?:0[1-9]|10)$")
    expected_category: str
    expected_service: str
    signal: FailureTriageGoldenSignal
    proposal: FailureTriageProposal


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
    if root is not None:
        api_cases_root = root.parent / "api-cases"
    else:
        api_source_tree_root = Path(__file__).resolve().parents[3] / "evals" / "api-cases"
        api_working_tree_root = Path.cwd() / "evals" / "api-cases"
        api_cases_root = (
            api_working_tree_root if api_working_tree_root.is_dir() else api_source_tree_root
        )
    api_case_results = (
        [
            evaluate_api_golden_case(path)
            for path in sorted(api_cases_root.iterdir())
            if path.is_dir()
        ]
        if api_cases_root.is_dir()
        else []
    )
    triage_root = cases_root.parent / "failure-triage"
    triage_result = evaluate_failure_triage_golden(triage_root)
    return {
        "schema_version": "agentic-qa.harness.golden-eval-result.v2",
        "passed": (
            bool(case_results)
            and bool(api_case_results)
            and all(result["passed"] for result in [*case_results, *api_case_results])
            and triage_result["passed"]
        ),
        "case_count": len(case_results),
        "cases": case_results,
        "api_case_count": len(api_case_results),
        "api_cases": api_case_results,
        "failure_triage_contract_safety": triage_result,
    }


def evaluate_failure_triage_golden(case_root: Path) -> dict[str, Any]:
    payload = json.loads((case_root / "golden.json").read_text(encoding="utf-8"))
    cases = [FailureTriageGoldenCase.model_validate(item) for item in payload["cases"]]
    results: list[dict[str, Any]] = []
    total_secrets = 0
    leaked_secrets = 0
    unsupported_high_confidence = 0
    unresolved_references = 0
    expectation_misses = 0
    for item in cases:
        signal = item.signal
        sanitized, _ = sanitize_log_text(signal.raw_message, preserve=set(signal.preserve))
        leaks = [value for value in signal.forbidden_values if value and value in sanitized]
        total_secrets += len(signal.forbidden_values)
        leaked_secrets += len(leaks)
        allowed_refs = set(signal.evidence_refs) | {"EXEC-0001"}
        supported_services = {signal.service}
        supported_exceptions = {signal.exception_type} if signal.exception_type else set()
        hypotheses = [item.proposal.primary, *item.proposal.alternatives]
        invalid_claims: list[str] = []
        bad_refs: list[str] = []
        for hypothesis in hypotheses:
            unresolved = sorted(set(hypothesis.evidence_refs) - allowed_refs)
            bad_refs.extend(unresolved)
            unsupported = (
                (hypothesis.service is not None and hypothesis.service not in supported_services)
                or (
                    hypothesis.exception_type is not None
                    and hypothesis.exception_type not in supported_exceptions
                )
                or not hypothesis.evidence_refs
                or bool(unresolved)
            )
            if hypothesis.confidence >= 0.7 and unsupported:
                invalid_claims.append(hypothesis.summary)
        expected = (
            item.proposal.primary.category == item.expected_category
            and item.proposal.primary.service == item.expected_service
        )
        unsupported_high_confidence += len(invalid_claims)
        unresolved_references += len(bad_refs)
        expectation_misses += int(not expected)
        results.append(
            {
                "case": item.id,
                "passed": not leaks and not invalid_claims and not bad_refs and expected,
                "category": item.proposal.primary.category,
                "service": item.proposal.primary.service,
                "secret_leaks": len(leaks),
                "unsupported_high_confidence_claims": len(invalid_claims),
                "unresolved_references": sorted(set(bad_refs)),
            }
        )
    expected_ids = {f"G{index:02d}" for index in range(1, 11)}
    complete = len(cases) == 10 and {item.id for item in cases} == expected_ids
    metrics = {
        "secret_leakage_rate": leaked_secrets / max(total_secrets, 1),
        "unsupported_high_confidence_claim_rate": unsupported_high_confidence / max(len(cases), 1),
        "unresolved_reference_count": unresolved_references,
        "category_service_miss_count": expectation_misses,
    }
    return {
        "schema_version": "agentic-qa.failure-triage-contract-safety-golden-result.v1",
        "passed": complete
        and all(item["passed"] for item in results)
        and metrics["secret_leakage_rate"] == 0
        and metrics["unsupported_high_confidence_claim_rate"] == 0
        and metrics["unresolved_reference_count"] == 0
        and metrics["category_service_miss_count"] == 0,
        "case_count": len(cases),
        "metrics": metrics,
        "cases": results,
    }


def run_failure_triage_live_eval(
    case_root: Path,
    *,
    model_gateway: Any,
) -> dict[str, Any]:
    payload = json.loads((case_root / "golden.json").read_text(encoding="utf-8"))
    cases = [FailureTriageGoldenCase.model_validate(item) for item in payload["cases"]]
    results: list[dict[str, Any]] = []
    unsupported_claims = 0
    unresolved_refs = 0
    secret_leaks = 0
    expectation_misses = 0
    route = ModelRoute(
        tier="pro",
        thinking="enabled",
        reasoning_effort="high",
        purpose="expert:failure_triager",
    )
    for item in cases:
        signal = item.signal
        sanitized, _ = sanitize_log_text(signal.raw_message, preserve=set(signal.preserve))
        allowed_refs = ["EXEC-0001", *signal.evidence_refs]
        prompt_payload = {
            "execution_facts": [
                {
                    "ref": "EXEC-0001",
                    "fact": {
                        "case_id": item.id,
                        "method": "POST",
                        "path_template": "/golden/failure",
                        "status": "failed",
                        "status_code": 500,
                        "request_dispatched": True,
                    },
                }
            ],
            "log_analysis": [
                {
                    "signal_id": "SIGNAL-0001",
                    "category": item.expected_category,
                    "service": signal.service,
                    "exception_type": signal.exception_type,
                    "normalized_message": sanitized,
                    "occurrence_count": 1,
                    "evidence_refs": signal.evidence_refs,
                }
            ],
            "allowed_evidence_refs": allowed_refs,
        }
        proposal = model_gateway.structured(
            system=SYSTEM,
            prompt=json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True),
            response_model=FailureTriageProposal,
            tools=[],
            route=route,
        )
        hypotheses = [proposal.primary, *proposal.alternatives]
        bad_refs = sorted(
            {
                ref
                for hypothesis in hypotheses
                for ref in hypothesis.evidence_refs
                if ref not in allowed_refs
            }
        )
        invalid_claims = [
            hypothesis.summary
            for hypothesis in hypotheses
            if hypothesis.confidence >= 0.7
            and (
                not hypothesis.evidence_refs
                or hypothesis.service not in {None, signal.service}
                or hypothesis.exception_type not in {None, signal.exception_type}
                or any(ref not in allowed_refs for ref in hypothesis.evidence_refs)
            )
        ]
        serialized = proposal.model_dump_json()
        leaks = [value for value in signal.forbidden_values if value and value in serialized]
        expected = (
            proposal.primary.category == item.expected_category
            and proposal.primary.service == item.expected_service
        )
        unsupported_claims += len(invalid_claims)
        unresolved_refs += len(bad_refs)
        secret_leaks += len(leaks)
        expectation_misses += int(not expected)
        results.append(
            {
                "case": item.id,
                "passed": not invalid_claims and not bad_refs and not leaks and expected,
                "category": proposal.primary.category,
                "service": proposal.primary.service,
                "exception_type": proposal.primary.exception_type,
                "evidence_refs": proposal.primary.evidence_refs,
            }
        )
    metrics = {
        "secret_leakage_count": secret_leaks,
        "unsupported_high_confidence_claim_count": unsupported_claims,
        "unresolved_reference_count": unresolved_refs,
        "category_service_miss_count": expectation_misses,
    }
    return {
        "schema_version": "agentic-qa.failure-triage-live-eval-result.v1",
        "passed": len(cases) == 10
        and all(item["passed"] for item in results)
        and all(value == 0 for value in metrics.values()),
        "case_count": len(cases),
        "metrics": metrics,
        "cases": results,
    }


def evaluate_api_golden_case(case_root: Path) -> dict[str, Any]:
    return evaluate_api_candidate_artifact(
        case_root,
        api_cases_content=(case_root / "candidate-api-cases.yml").read_text(encoding="utf-8"),
        artifact_name="candidate-api-cases.yml",
    )


def evaluate_api_candidate_artifact(
    case_root: Path,
    *,
    api_cases_content: str,
    artifact_name: str = "generated api_test_draft/raw.yml",
) -> dict[str, Any]:
    expected = ApiGoldenExpectation.model_validate_json(
        (case_root / "api-expectations.json").read_text(encoding="utf-8")
    )
    validation_issues: list[dict[str, Any]] = []
    try:
        payload = yaml.safe_load(api_cases_content)
        candidate = load_api_test_cases(payload)
        validate_api_case_runtime_definitions(candidate.cases)
    except ValidationError as exc:
        validation_issues = exc.errors(include_input=False, include_url=False)
        candidate = None
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        validation_issues = [{"type": type(exc).__name__, "msg": str(exc)}]
        candidate = None

    covered_points = _api_covered_points(candidate) if candidate is not None else set()
    required_points = set(expected.must_cover_points)
    covered = required_points & covered_points
    coverage_rate = len(covered) / len(required_points)
    contract_rate = 0.0
    contract_issues: list[dict[str, Any]] = []
    contract_check_count = 0
    if candidate is not None:
        try:
            openapi = yaml.safe_load((case_root / "source.openapi.yml").read_text(encoding="utf-8"))
            referenced_sources = {
                reference.source_path
                for case in candidate.cases
                if case.contract_status == "confirmed"
                for reference in case.source_refs
                if reference.source_type == "openapi" and reference.confidence == "high"
            }
            if len(referenced_sources) != 1:
                raise ValueError(
                    "API Golden requires exactly one referenced complete OpenAPI source"
                )
            inspection = inspect_openapi(openapi, source=next(iter(referenced_sources)))
            contract_result = validate_api_contracts(candidate, [inspection])
            contract_rate = contract_result.semantic_rate
            contract_check_count = contract_result.check_count
            contract_issues = [issue.model_dump(mode="json") for issue in contract_result.issues]
        except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            contract_issues = [
                {
                    "code": "openapi_contract_unavailable",
                    "case_id": "",
                    "instance_id": "",
                    "location": "source.openapi.yml",
                    "message": str(exc),
                }
            ]
    score = 0.6 * coverage_rate + 0.4 * contract_rate if not validation_issues else 0.0
    return {
        "case": case_root.name,
        "passed": (
            score >= expected.minimum_score and not validation_issues and not contract_issues
        ),
        "score": round(score, 4),
        "minimum_score": expected.minimum_score,
        "metrics": {
            "coverage_rate": round(coverage_rate, 4),
            "contract_semantic_rate": round(contract_rate, 4),
            "contract_check_count": contract_check_count,
            "contract_issue_count": len(contract_issues),
            "case_count": len(candidate.cases) if candidate is not None else 0,
            "dataset_count": (
                sum(
                    len(parse_api_case_variables(case.variables).datasets)
                    for case in candidate.cases
                )
                if candidate is not None
                else 0
            ),
            "cleanup_count": (
                sum(len(parse_api_cleanup_steps(case.cleanup)) for case in candidate.cases)
                if candidate is not None
                else 0
            ),
        },
        "missing_coverage": sorted(required_points - covered_points),
        "validation_issues": validation_issues,
        "contract_issues": contract_issues,
        "candidate_artifact": artifact_name,
    }


def _api_covered_points(candidate: ApiTestCasesDraft) -> set[str]:
    points: set[str] = set()
    for case in candidate.cases:
        points.add(f"case:{case.id}")
        points.add(f"operation:{case.request.method} {case.request.path}")
        if case.contract_status == "confirmed":
            points.add(f"confirmed-openapi:{case.id}")
        variables = parse_api_case_variables(case.variables)
        cleanup = parse_api_cleanup_steps(case.cleanup)
        for dataset in variables.datasets:
            points.add(f"dataset:{case.id}:{dataset.id}")
        for name, extraction in variables.extract.items():
            points.add(f"extract:{case.id}:{name}:{extraction.source}")
        request_references = variable_references(case.request.model_dump(mode="python"))
        points.update(f"reference:{case.id}:{name}" for name in request_references)
        points.update(f"assertion:{assertion.type}" for assertion in case.assertions)
        for step in cleanup:
            points.add(f"cleanup:{case.id}:{step.id}:{step.request.method} {step.request.path}")
            cleanup_references = variable_references(step.request.model_dump(mode="python"))
            points.update(f"cleanup-reference:{case.id}:{name}" for name in cleanup_references)
            points.update(f"assertion:{assertion.type}" for assertion in step.assertions)
    return points


def _covered_points(
    testcase_set: TestCaseSet,
    rendered: str,
    expected_catalog: RequirementCatalog,
) -> set[str]:
    points = {mapping.rule_id for mapping in testcase_set.coverage}
    folded = rendered.casefold()
    for case in testcase_set.cases:
        points.add(f"type:{case.test_type}")
        case_semantics = " ".join(
            [
                case.test_type,
                case.title,
                *case.preconditions,
                *case.test_data,
                *case.steps,
                *case.expected_results,
                *case.assertions,
            ]
        )
        points.update(f"type:{name}" for name in _canonical_test_types(case_semantics))
    for rule in expected_catalog.rules:
        for boundary in rule.boundaries:
            points.update(
                f"boundary:{value}" for value in boundary.values if value.casefold() in folded
            )
        for transition in rule.state_transitions:
            if (
                transition.from_state.casefold() in folded
                and transition.to_state.casefold() in folded
                and _transition_event_covered(transition.event, folded)
            ):
                points.add(
                    f"transition:{transition.from_state}->{transition.event}->{transition.to_state}"
                )
    return points


def _canonical_test_types(value: str) -> set[str]:
    folded = value.casefold()
    aliases = {
        "边界": ("边界", "boundary"),
        "幂等": ("幂等", "idempot"),
        "并发": ("并发", "concurr"),
        "状态迁移": ("状态迁移", "状态流转", "transition"),
        "异常": ("异常", "error", "failure"),
        "反向": ("反向", "negative"),
    }
    return {
        canonical
        for canonical, markers in aliases.items()
        if any(marker in folded for marker in markers)
    }


def _transition_event_covered(event: str, folded_rendered: str) -> bool:
    alternatives = [
        item.strip().casefold() for item in re.split(r"\s*(?:或|/|、)\s*", event) if item.strip()
    ]
    if any(item in folded_rendered for item in alternatives):
        return True
    rendered_grams = _character_bigrams(folded_rendered)
    return any(
        grams and len(grams & rendered_grams) / len(grams) >= 0.6
        for item in alternatives
        if (grams := _character_bigrams(item))
    )


def _rule_aliases(
    expected: RequirementCatalog,
    candidate: RequirementCatalog,
) -> dict[str, str]:
    expected_ids = [rule.rule_id for rule in expected.rules]
    candidate_ids = [rule.rule_id for rule in candidate.rules]
    aliases = {rule_id: rule_id for rule_id in set(expected_ids) & set(candidate_ids)}
    unmatched_expected = [rule_id for rule_id in expected_ids if rule_id not in aliases]
    unmatched_candidate = [rule_id for rule_id in candidate_ids if rule_id not in aliases]
    expected_by_id = {rule.rule_id: rule for rule in expected.rules}
    candidate_by_id = {rule.rule_id: rule for rule in candidate.rules}
    for candidate_id in unmatched_candidate:
        scored = sorted(
            (
                (
                    _rule_semantic_containment(
                        candidate_by_id[candidate_id],
                        expected_by_id[expected_id],
                    ),
                    expected_id,
                )
                for expected_id in unmatched_expected
            ),
            reverse=True,
        )
        if scored and scored[0][0] >= 0.28:
            aliases[candidate_id] = scored[0][1]
    unmatched_expected = [
        rule_id for rule_id in unmatched_expected if rule_id not in set(aliases.values())
    ]
    unmatched_candidate = [rule_id for rule_id in unmatched_candidate if rule_id not in aliases]
    if len(unmatched_expected) == len(unmatched_candidate):
        aliases.update(zip(unmatched_candidate, unmatched_expected, strict=True))
    return aliases


def _rule_semantic_containment(
    candidate: RequirementRule,
    expected: RequirementRule,
) -> float:
    candidate_grams = _character_bigrams(_rule_semantic_text(candidate))
    expected_grams = _character_bigrams(_rule_semantic_text(expected))
    if not candidate_grams or not expected_grams:
        return 0.0
    return len(candidate_grams & expected_grams) / min(
        len(candidate_grams),
        len(expected_grams),
    )


def _rule_semantic_text(rule: RequirementRule) -> str:
    return " ".join(
        [
            rule.title,
            rule.condition,
            rule.outcome,
            *(f"{boundary.field} {' '.join(boundary.values)}" for boundary in rule.boundaries),
            *(
                f"{transition.from_state} {transition.event} {transition.to_state}"
                for transition in rule.state_transitions
            ),
        ]
    )


def _character_bigrams(value: str) -> set[str]:
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())
    return {normalized[index : index + 2] for index in range(max(len(normalized) - 1, 0))}


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
