from pathlib import Path
from shutil import copytree

from harness.testing.evals import recorded_model_gateway, run_live_eval
from harness.testing.golden import evaluate_golden_case, run_golden_eval


def test_golden_eval_measures_artifact_quality() -> None:
    result = run_golden_eval()

    assert result["passed"]
    assert result["case_count"] == 5
    assert all(case["score"] >= case["minimum_score"] for case in result["cases"])
    assert all(case["metrics"]["rule_recall"] == 1 for case in result["cases"])
    assert all(case["metrics"]["coverage_rate"] == 1 for case in result["cases"])
    assert all("baseline_gap" in case for case in result["cases"])
    assert all(
        case["candidate_artifacts"]["testcases"] == "candidate-testcases.md"
        for case in result["cases"]
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


def test_live_eval_scores_generated_candidate_not_only_run_status(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "harness.infrastructure.llm.gateway.model_gateway_from_env",
        lambda: recorded_model_gateway(),
    )
    output_root = tmp_path / "live-eval-artifacts"
    monkeypatch.setenv("AGENTIC_QA_LIVE_EVAL_OUTPUT", str(output_root))

    result = run_live_eval()

    assert result["status"] == "needs_human_review"
    assert result["golden"] is not None
    assert not result["golden"]["passed"]
    assert not result["passed"]
    assert (output_root / "source-bundle.json").is_file()
    assert (output_root / "requirement_analysis/raw.md").is_file()
    assert (output_root / "testcases/quality-report.json").is_file()
    assert (output_root / "testcases/generation-report.json").is_file()
