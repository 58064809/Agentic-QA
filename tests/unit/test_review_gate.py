from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_fixtures import create_runtime_repo  # noqa: E402

from runtime.review import ReviewDecision, ReviewIntent, process_review_gate  # noqa: E402
from runtime.review.intent_parser import (  # noqa: E402
    decision_from_llm_response,
    parse_review_decision_fallback,
)


def read_review(repo_root: Path, name: str) -> dict:
    path = repo_root / "prd/demo-requirement/reviews" / name
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_natural_language_approve_does_not_confirm_or_write_artifact(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = process_review_gate(
        repo_root=repo_root,
        prd_path="prd/demo-requirement",
        run_id="run-1",
        user_input="可以了，发布吧",
        artifact_keys=["testcases"],
    )

    assert result.success
    assert result.decision.intent == ReviewIntent.APPROVE
    assert result.approved_for_promote
    review = read_review(repo_root, "testcases.review.yml")
    assert review["status"] == "approved"
    assert review["decision"] == "approve"
    assert not (repo_root / "prd/demo-requirement/artifacts/testcases.md").exists()


def test_negative_publish_language_does_not_approve():
    decision = parse_review_decision_fallback("先不要发布")

    assert decision.intent in {ReviewIntent.HOLD, ReviewIntent.REJECT}
    assert decision.intent != ReviewIntent.APPROVE


def test_revision_request_enters_needs_changes(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = process_review_gate(
        repo_root=repo_root,
        prd_path="prd/demo-requirement",
        run_id="run-1",
        user_input="补充异常流程和权限校验",
        artifact_keys=["testcases"],
    )

    assert result.success
    assert result.decision.intent == ReviewIntent.REVISE
    review = read_review(repo_root, "testcases.review.yml")
    assert review["status"] == "needs_changes"
    assert "补充异常流程和权限校验" in review["required_changes"]


def test_specific_artifact_approval_targets_testcases(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = process_review_gate(
        repo_root=repo_root,
        prd_path="prd/demo-requirement",
        run_id="run-1",
        user_input="只发布测试用例，不发布需求分析",
        artifact_keys=["requirement_analysis", "testcases"],
    )

    assert result.success
    assert result.target_artifacts == ["testcases"]
    assert result.decision.target_artifact == "testcases"
    assert read_review(repo_root, "testcases.review.yml")["status"] == "approved"
    analysis_path = repo_root / "prd/demo-requirement/reviews/requirement-analysis.review.yml"
    assert not analysis_path.exists()


def test_llm_invalid_json_enters_clarify():
    decision = decision_from_llm_response("不是 JSON")

    assert decision.intent == ReviewIntent.CLARIFY
    assert decision.requires_confirmation


def test_low_confidence_requires_confirmation():
    decision = decision_from_llm_response(
        '{"intent":"approve","target_artifact":"testcases","confidence":0.5,'
        '"reason":"不确定","requires_confirmation":false}'
    )

    assert decision.intent == ReviewIntent.APPROVE
    assert decision.requires_confirmation


def test_confirmed_status_rejects_reapprove(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    review_path = repo_root / "prd/demo-requirement/reviews/testcases.review.yml"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        yaml.safe_dump(
            {
                "artifact": "artifacts/testcases.md",
                "artifact_type": "testcases",
                "status": "confirmed",
                "decision": "promoted",
                "run_id": "run-1",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = process_review_gate(
        repo_root=repo_root,
        prd_path="prd/demo-requirement",
        run_id="run-1",
        user_input="可以了，发布吧",
        artifact_keys=["testcases"],
    )

    assert not result.success
    assert any("confirmed" in error for error in result.errors)
    assert read_review(repo_root, "testcases.review.yml")["status"] == "confirmed"


def test_confirmed_previous_run_can_approve_new_candidate(tmp_path):
    repo_root = create_runtime_repo(tmp_path)
    review_path = repo_root / "prd/demo-requirement/reviews/testcases.review.yml"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(
        yaml.safe_dump(
            {
                "artifact": "artifacts/testcases.md",
                "artifact_type": "testcases",
                "status": "confirmed",
                "decision": "promoted",
                "run_id": "run-1",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = process_review_gate(
        repo_root=repo_root,
        prd_path="prd/demo-requirement",
        run_id="run-2",
        user_input="可以了，发布吧",
        artifact_keys=["testcases"],
    )

    assert result.success
    assert result.approved_for_promote
    review = read_review(repo_root, "testcases.review.yml")
    assert review["status"] == "approved"
    assert review["run_id"] == "run-2"


def test_multifact_without_target_enters_clarify(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = process_review_gate(
        repo_root=repo_root,
        prd_path="prd/demo-requirement",
        run_id="run-1",
        user_input="可以了，发布吧",
        artifact_keys=["requirement_analysis", "testcases"],
    )

    assert not result.success
    assert result.decision.intent == ReviewIntent.CLARIFY
    assert result.decision.requires_confirmation


def test_process_review_gate_defaults_reject_without_target_to_all(tmp_path):
    repo_root = create_runtime_repo(tmp_path)

    result = process_review_gate(
        repo_root=repo_root,
        prd_path="prd/demo-requirement",
        run_id="run-1",
        user_input="涓嶉€氳繃",
        artifact_keys=["requirement_analysis", "testcases"],
        decision=ReviewDecision(
            intent=ReviewIntent.REJECT,
            confidence=1,
            reason="reject all candidates",
        ),
    )

    assert result.success
    assert result.decision.target_artifact == "all"
    assert result.target_artifacts == ["requirement_analysis", "testcases"]
    assert read_review(repo_root, "requirement-analysis.review.yml")["status"] == "rejected"
    assert read_review(repo_root, "testcases.review.yml")["status"] == "rejected"


def test_explicit_review_decision_schema_is_pydantic():
    decision = ReviewDecision(
        intent=ReviewIntent.APPROVE,
        target_artifact="testcases",
        confidence=1,
        reason="unit test",
    )

    assert decision.model_dump(mode="json")["intent"] == "approve"


def test_review_decision_schema_accepts_all_target():
    decision = ReviewDecision(
        intent=ReviewIntent.APPROVE,
        target_artifact="all",
        confidence=1,
        reason="approve all candidates",
    )

    assert decision.target_artifact == "all"
