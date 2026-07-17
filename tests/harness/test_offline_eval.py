from harness.evals import run_offline_eval


def test_offline_eval_covers_complete_review_loop() -> None:
    result = run_offline_eval()
    assert result["passed"]
    assert result["artifact_count"] == 9
