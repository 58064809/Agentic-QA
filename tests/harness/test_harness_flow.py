from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_qa import Harness, ReviewDecision, TaskRequest
from agentic_qa.budget import BudgetLimits
from agentic_qa.model import CallableModelGateway


def test_run_review_and_deterministic_promote(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.init_workspace("demo")
    snapshot = harness.run(
        TaskRequest(
            workspace="demo",
            goal="验证登录和退出",
            expected_artifacts=["testcases", "requirement_analysis"],
        )
    )

    assert snapshot.status == "needs_human_review"
    assert {item.artifact for item in snapshot.candidates} == {
        "testcases",
        "requirement_analysis",
    }
    assert not (tmp_path / "workspaces/demo/published/testcases/current.md").exists()

    with pytest.raises(ValueError, match="多候选审核必须指定"):
        harness.resume(
            snapshot.run_id,
            ReviewDecision(intent="approve", reason="reviewed"),
        )

    published = harness.resume(
        snapshot.run_id,
        ReviewDecision(intent="approve", target_artifact="all", reason="reviewed"),
    )
    assert published.status == "published"
    assert (tmp_path / "workspaces/demo/published/testcases/current.md").is_file()
    assert harness.inspect(snapshot.run_id).review_status["testcases"] == "confirmed"


def test_checkpoint_and_events_capture_parallel_dispatch(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.init_workspace("demo")
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test login"))
    run = tmp_path / "workspaces/demo/runs" / snapshot.run_id
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    delegated = [event for event in events if event["type"] == "tasks_delegated"]
    assert delegated[0]["data"]["task_ids"] == ["analyze_requirements", "analyze_risks"]
    assert len(list((run / "checkpoints").glob("*.json"))) >= 2


def test_budget_exhaustion_produces_reviewable_partial(tmp_path: Path) -> None:
    model = CallableModelGateway(lambda **_kwargs: {"summary": "unused"})
    harness = Harness(
        tmp_path,
        model_gateway=model,
        budget_limits=BudgetLimits(max_model_calls=0),
    )
    harness.init_workspace("demo")
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test login"))
    assert snapshot.status == "partial"
    assert snapshot.candidates[0].status == "partial"
    assert "model call budget exceeded" in snapshot.errors


def test_candidate_is_never_overwritten(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.init_workspace("demo")
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test login"))
    candidate = snapshot.candidates[0]
    with pytest.raises(FileExistsError, match="不允许覆盖"):
        harness.store.write_candidate(
            workspace="demo",
            run_id=snapshot.run_id,
            artifact=candidate.artifact,
            content="replacement",
        )


def test_stream_emits_events_and_snapshot_is_inspectable(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.init_workspace("demo")
    events = list(harness.stream(TaskRequest(workspace="demo", goal="test login")))
    assert events[-1].type == "review_required"
    snapshot = harness.inspect(events[-1].run_id)
    assert snapshot.status == "needs_human_review"
