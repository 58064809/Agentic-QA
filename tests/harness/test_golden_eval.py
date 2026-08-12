import json
from pathlib import Path
from shutil import copytree

import yaml

from harness.domain.schemas.qa_design import RequirementCatalog
from harness.testing.evals import (
    recorded_model_gateway,
    run_failure_triage_model_live_eval,
    run_live_eval,
)
from harness.testing.golden import (
    _rule_aliases,
    evaluate_api_candidate_artifact,
    evaluate_api_golden_case,
    evaluate_failure_triage_golden,
    evaluate_golden_case,
    run_golden_eval,
)


def test_golden_eval_measures_artifact_quality() -> None:
    result = run_golden_eval()

    assert result["passed"]
    assert result["case_count"] == 6
    assert result["api_case_count"] == 1
    assert result["api_cases"][0]["metrics"]["coverage_rate"] == 1
    assert result["failure_triage_contract_safety"]["case_count"] == 10
    assert result["failure_triage_contract_safety"]["metrics"] == {
        "secret_leakage_rate": 0.0,
        "unsupported_high_confidence_claim_rate": 0.0,
        "unresolved_reference_count": 0,
        "category_service_miss_count": 0,
    }
    assert all(case["score"] >= case["minimum_score"] for case in result["cases"])
    assert all(case["metrics"]["rule_recall"] == 1 for case in result["cases"])
    assert all(case["metrics"]["coverage_rate"] == 1 for case in result["cases"])
    assert all("baseline_gap" in case for case in result["cases"])
    assert all(
        case["candidate_artifacts"]["testcases"] == "candidate-testcases.md"
        for case in result["cases"]
    )


def test_failure_triage_golden_blocks_unsupported_high_confidence_claim(
    tmp_path: Path,
) -> None:
    source = Path("evals/failure-triage/golden.json")
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["cases"][0]["proposal"]["primary"]["service"] = "invented-service"
    root = tmp_path / "failure-triage"
    root.mkdir()
    (root / "golden.json").write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_failure_triage_golden(root)

    assert not result["passed"]
    assert result["metrics"]["unsupported_high_confidence_claim_rate"] > 0


def test_failure_triage_live_eval_calls_current_prompt_and_model_gateway() -> None:
    captured: list[dict[str, object]] = []

    def callback(**kwargs):
        captured.append(kwargs)
        context = json.loads(kwargs["prompt"])
        signal = context["log_analysis"][0]
        category = signal["category"]
        return {
            "primary": {
                "category": category,
                "service": signal["service"],
                "exception_type": signal["exception_type"],
                "summary": "Cited live-eval hypothesis",
                "confidence": 0.9,
                "evidence_refs": signal["evidence_refs"],
            },
            "alternatives": [],
            "recommended_actions": [],
        }

    from harness.infrastructure.llm.gateway import CallableModelGateway

    result = run_failure_triage_model_live_eval(model_gateway=CallableModelGateway(callback))

    assert result["passed"]
    assert result["case_count"] == 10
    assert len(captured) == 10
    assert all(call["tools"] == [] for call in captured)
    assert all("failure_triager" in str(call["system"]) for call in captured)


def test_api_golden_eval_rejects_missing_data_flow_and_cleanup() -> None:
    case_root = Path("evals/api-cases/order-lifecycle")
    passing = evaluate_api_golden_case(case_root)
    payload = yaml.safe_load((case_root / "candidate-api-cases.yml").read_text(encoding="utf-8"))
    payload["cases"][0]["cleanup"] = []
    payload["cases"][1]["request"]["query"]["id"] = "fixed-order"

    result = evaluate_api_candidate_artifact(
        case_root,
        api_cases_content=yaml.safe_dump(payload, sort_keys=False),
    )

    assert passing["passed"]
    assert passing["score"] == 1
    assert not result["passed"]
    assert 0 < result["score"] < 1
    assert result["validation_issues"] == []


def test_api_golden_eval_scores_openapi_contract_semantics() -> None:
    case_root = Path("evals/api-cases/order-lifecycle")
    payload = yaml.safe_load((case_root / "candidate-api-cases.yml").read_text(encoding="utf-8"))
    payload["cases"][0]["request"]["body"]["invented"] = "unsupported"
    payload["cases"][0]["assertions"][0]["expected"] = 202
    payload["cases"][1]["assertions"][1]["path"] = "$.data.unknown"

    result = evaluate_api_candidate_artifact(
        case_root,
        api_cases_content=yaml.safe_dump(payload, sort_keys=False),
    )

    assert not result["passed"]
    assert result["metrics"]["contract_semantic_rate"] < 1
    assert result["contract_issues"]
    assert {issue["code"] for issue in result["contract_issues"]} >= {
        "schema_mismatch",
        "undeclared_response_status",
        "undeclared_response_json_path",
    }
    assert any(
        issue["instance_id"] == "API-ORDER-CREATE::single-item"
        and issue["location"].startswith("request.body")
        for issue in result["contract_issues"]
    )


def test_golden_eval_does_not_score_the_human_baseline_as_candidate(
    tmp_path: Path,
) -> None:
    source = Path("evals/cases/login-lock")
    case_root = tmp_path / "login-lock"
    copytree(source, case_root)
    candidate = case_root / "candidate-testcases.md"
    content = "\n".join(
        line
        for line in candidate.read_text(encoding="utf-8").splitlines()
        if not line.startswith("| TC-LOGIN-003 ")
    ).replace(", TC-LOGIN-003", "")
    candidate.write_text(content + "\n", encoding="utf-8")

    result = evaluate_golden_case(case_root)

    assert result["baseline_score"] == 1
    assert result["score"] < result["baseline_score"]
    assert not result["passed"]


def test_rule_aliases_match_atomic_candidate_rules_to_composite_expectation() -> None:
    expected = RequirementCatalog.model_validate_json(
        Path("evals/cases/lottery-assistance/expectations.json").read_text(encoding="utf-8")
    )
    composite = next(rule for rule in expected.rules if rule.rule_id == "LOTTERY-003")
    candidate = expected.model_copy(
        update={
            "rules": [
                *[rule for rule in expected.rules if rule.rule_id != composite.rule_id],
                composite.model_copy(
                    update={
                        "rule_id": "SRC-ATOMIC-001",
                        "title": "同一抽奖请求重试保持幂等",
                        "condition": "网络重试复用同一抽奖请求ID",
                        "outcome": "不得重复扣次或重复发奖",
                    }
                ),
                composite.model_copy(
                    update={
                        "rule_id": "SRC-ATOMIC-002",
                        "title": "异常未产生结果时退还机会",
                        "condition": "系统异常且没有有效抽奖结果",
                        "outcome": "自动退还本次抽奖机会",
                    }
                ),
            ]
        }
    )

    aliases = _rule_aliases(expected, candidate)

    assert aliases["SRC-ATOMIC-001"] == "LOTTERY-003"
    assert aliases["SRC-ATOMIC-002"] == "LOTTERY-003"


def test_live_eval_scores_generated_candidate_not_only_run_status(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "live-eval-artifacts"

    result = run_live_eval(model_gateway=recorded_model_gateway(), output_root=output_root)

    assert result["case"] == "login-lock"
    assert result["status"] == "needs_human_review"
    assert result["golden"] is not None
    assert not result["golden"]["passed"]
    assert not result["passed"]
    assert (output_root / "source-bundle.json").is_file()
    assert (output_root / "requirement_analysis/raw.md").is_file()
    assert (output_root / "testcases/quality-report.json").is_file()
    assert (output_root / "testcases/generation-report.json").is_file()


def test_live_eval_selects_configured_case() -> None:
    result = run_live_eval("lottery-assistance", model_gateway=recorded_model_gateway())

    assert result["case"] == "lottery-assistance"
    assert result["status"] == "needs_human_review"
    assert result["golden"]["case"] == "lottery-assistance"


def test_live_eval_scores_api_candidate_with_api_golden(tmp_path: Path) -> None:
    output_root = tmp_path / "api-live-eval-artifacts"

    result = run_live_eval(
        "order-lifecycle",
        model_gateway=recorded_model_gateway(),
        output_root=output_root,
    )

    assert result["case"] == "order-lifecycle"
    assert result["status"] == "needs_human_review"
    assert result["candidate_count"] == 1
    assert result["golden"] is not None
    assert result["golden"]["candidate_artifact"] == "generated api_test_draft/raw.yml"
    assert not result["passed"]
    assert (output_root / "api_test_draft/raw.yml").is_file()
    assert not (output_root / "api_test_draft/raw.md").exists()
    assert (output_root / "api_test_draft/quality-report.json").is_file()
    assert (output_root / "api_test_draft/generation-report.json").is_file()
