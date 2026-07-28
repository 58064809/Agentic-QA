from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.application.qa_design import (
    parse_requirement_markdown,
    parse_testcase_markdown,
    render_requirement_catalog,
    render_testcase_set,
)
from harness.application.quality import QualityContext
from harness.application.source import (
    SourceBundle,
    SourceCompleteness,
    SourceDocument,
    SourceIngestionLimits,
)
from harness.domain.schemas.qa_design import (
    RequirementCatalog,
    validate_testcase_set,
)
from harness.domain.schemas.qa_design import (
    TestCasePatch as QATestCasePatch,
)
from harness.domain.schemas.qa_design import (
    TestCaseSet as QATestCaseSet,
)
from harness.infrastructure.quality.declarative import DeclarativeQualityStrategy
from harness.infrastructure.quality.generic import GenericArtifactStrategy
from harness.infrastructure.workflow.engine import (
    _testcase_rule_batches,
    _validate_targeted_testcase_patch,
)

CASES = Path(__file__).resolve().parents[2] / "evals" / "cases"


def _catalog(case: str = "login-lock") -> RequirementCatalog:
    return RequirementCatalog.model_validate_json(
        (CASES / case / "expectations.json").read_text(encoding="utf-8")
    )


def _testcase_set(case: str = "login-lock") -> QATestCaseSet:
    return QATestCaseSet.model_validate_json(
        (CASES / case / "baseline-testcases.json").read_text(encoding="utf-8")
    )


def _context(artifact: str, source: str = "") -> QualityContext:
    document = SourceDocument(
        path="source.md",
        raw_sha256="sha256:" + "1" * 64,
        parsed_sha256="sha256:" + "2" * 64,
        byte_size=len(source.encode()),
        text=source,
        completeness=SourceCompleteness.COMPLETE,
    )
    return QualityContext(
        workspace_id="demo",
        run_id="run-1",
        artifact=artifact,
        source_bundle=SourceBundle(
            parser_version="test",
            limits=SourceIngestionLimits(),
            documents=(document,),
            completeness=SourceCompleteness.COMPLETE,
            bundle_hash="sha256:" + "3" * 64,
        ),
    )


def test_typed_design_round_trips_through_deterministic_markdown() -> None:
    catalog = _catalog()
    testcase_set = _testcase_set()

    assert not validate_testcase_set(catalog, testcase_set)
    assert "## 规则目录" in render_requirement_catalog(catalog)
    parsed = parse_testcase_markdown(render_testcase_set(testcase_set))
    assert [case.case_id for case in parsed.cases] == [case.case_id for case in testcase_set.cases]
    assert parsed.coverage == testcase_set.coverage
    parsed_catalog = parse_requirement_markdown(render_requirement_catalog(catalog))
    assert [rule.rule_id for rule in parsed_catalog.rules] == [
        rule.rule_id for rule in catalog.rules
    ]
    assert parsed_catalog.rules[0].boundaries == catalog.rules[0].boundaries
    assert parsed_catalog.rules[0].state_transitions == catalog.rules[0].state_transitions


def test_cross_catalog_validation_reports_missing_boundary_and_rule() -> None:
    catalog = _catalog()
    testcase_set = _testcase_set().model_copy(
        update={
            "cases": _testcase_set().cases[:1],
            "coverage": [],
        }
    )

    issues = validate_testcase_set(catalog, testcase_set)

    assert {issue.code for issue in issues} >= {
        "confirmed_rule_uncovered",
        "boundary_value_uncovered",
        "state_transition_uncovered",
    }


def test_rule_batches_are_bounded_and_preserve_catalog_order() -> None:
    catalog = _catalog("order-refund")

    batches = _testcase_rule_batches(catalog, None, batch_size=1)

    assert [batch["batch_id"] for batch in batches] == ["rules-001", "rules-002"]
    assert [batch["rule_ids"] for batch in batches] == [
        ["REFUND-001"],
        ["REFUND-002"],
    ]


def test_targeted_patch_cannot_rewrite_unaffected_rule() -> None:
    current = _testcase_set("order-refund")
    unaffected = next(case for case in current.cases if "REFUND-002" in case.rule_ids)
    patch = QATestCasePatch(replace_cases=[unaffected])
    feedback = [
        {
            "kind": "quality_gate",
            "error": json.dumps(
                {"blockers": [{"rule_id": "REFUND-001", "case_id": "TC-REFUND-001"}]}
            ),
        }
    ]

    with pytest.raises(ValueError, match="outside reviewer blocker scope"):
        _validate_targeted_testcase_patch(patch, current, feedback)


def test_generic_gate_rejects_dangling_coverage_reference() -> None:
    content = render_testcase_set(_testcase_set()).replace("TC-LOGIN-003", "TC-LOGIN-999", 1)

    result = GenericArtifactStrategy().evaluate(_context("testcases"), content)

    assert {issue.code for issue in result.issues} == {"invalid_testcase_set"}


def test_generic_gate_accepts_source_supported_chinese_implementation_suffix() -> None:
    original = _testcase_set()
    first_case = original.cases[0].model_copy(
        update={
            "title": "验证活动页面",
            "preconditions": ["活动页面可访问"],
            "test_data": ["有效测试用户"],
            "steps": ["用户进入活动页面"],
            "expected_results": ["活动页面展示活动内容"],
            "assertions": ["观察活动页面内容"],
            "pending_items": [],
        }
    )
    first_mapping = original.coverage[0].model_copy(update={"case_ids": [first_case.case_id]})
    testcase_set = QATestCaseSet(cases=[first_case], coverage=[first_mapping])

    result = GenericArtifactStrategy().evaluate(
        _context("testcases", "产品提供活动页面。"),
        render_testcase_set(testcase_set),
    )

    assert "unsupported_implementation_detail" not in {issue.code for issue in result.issues}


def test_generic_gate_rejects_invented_implementation_suffix() -> None:
    original = _testcase_set()
    first_case = original.cases[0].model_copy(
        update={
            "title": "验证抽奖动作",
            "preconditions": ["活动已开始"],
            "test_data": ["有效测试用户"],
            "steps": ["调用抽奖接口"],
            "expected_results": ["抽奖动作产生可观察结果"],
            "assertions": ["记录业务结果"],
            "pending_items": [],
        }
    )
    first_mapping = original.coverage[0].model_copy(update={"case_ids": [first_case.case_id]})
    testcase_set = QATestCaseSet(cases=[first_case], coverage=[first_mapping])

    result = GenericArtifactStrategy().evaluate(
        _context("testcases", "产品提供活动页面。"),
        render_testcase_set(testcase_set),
    )

    assert "unsupported_implementation_detail" in {issue.code for issue in result.issues}


def test_declarative_policy_enforces_boundaries_without_business_python() -> None:
    strategy = DeclarativeQualityStrategy.from_manifest(
        Path("src/harness/manifests/quality/city-opening-rewards.yml")
    )
    content = render_testcase_set(_testcase_set("city-opening-rewards"))
    source = (CASES / "city-opening-rewards" / "source.md").read_text(encoding="utf-8")

    result = strategy.evaluate(_context("testcases", source), content)

    assert not result.issues


def test_declarative_policy_checks_required_condition_fields() -> None:
    strategy = DeclarativeQualityStrategy.from_manifest(
        Path("src/harness/manifests/quality/city-opening-rewards.yml")
    )
    content = render_testcase_set(_testcase_set("city-opening-rewards")).replace(
        "participant_count", "人数"
    )
    source = (CASES / "city-opening-rewards" / "source.md").read_text(encoding="utf-8")

    result = strategy.evaluate(_context("testcases", source), content)

    assert {issue.code for issue in result.issues} == {"required_rule_conditions_uncovered"}


def test_declarative_policy_matches_generated_rule_namespace_by_conditions() -> None:
    strategy = DeclarativeQualityStrategy.from_manifest(
        Path("src/harness/manifests/quality/city-opening-rewards.yml")
    )
    original = _testcase_set("city-opening-rewards")
    generated_rule_id = "SRC-1234ABCD-001"
    generated = original.model_copy(
        update={
            "cases": [
                case.model_copy(update={"rule_ids": [generated_rule_id]}) for case in original.cases
            ],
            "coverage": [
                mapping.model_copy(update={"rule_id": generated_rule_id})
                for mapping in original.coverage
            ],
        }
    )
    source = (CASES / "city-opening-rewards" / "source.md").read_text(encoding="utf-8")

    result = strategy.evaluate(
        _context("testcases", source),
        render_testcase_set(generated),
    )

    assert not result.issues
