from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import (
    ArtifactDiffEndpoint,
    ArtifactVariant,
    CreateWorkspaceCommand,
    GetArtifactDiffQuery,
    Harness,
    ResumeRunCommand,
    ReviewDecision,
    ReviewRunCommand,
    RunRef,
    StartRunCommand,
)
from harness.testing.evals import recorded_model_gateway


def _harness(path: Path) -> Harness:
    return Harness(path, model_gateway=recorded_model_gateway())


def _create(harness: Harness, workspace_id: str = "demo") -> Path:
    return harness.create_workspace(CreateWorkspaceCommand(workspace_id=workspace_id))


def test_v2_start_get_review_and_promote(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    workspace = _create(harness)

    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test login"))

    assert snapshot.schema_version == "agentic-qa.harness.run-snapshot.v2"
    assert snapshot.status == "needs_human_review"
    assert harness.get_run(RunRef(workspace_id="demo", run_id=snapshot.run_id)) == snapshot

    published = harness.review_run(
        ReviewRunCommand(
            workspace_id="demo",
            run_id=snapshot.run_id,
            decision=ReviewDecision(
                intent="approve",
                target_artifact="all",
                reason="human approval",
                reviewed_by="qa_owner",
                versions=[
                    candidate.version_ref(ArtifactVariant.RAW) for candidate in snapshot.candidates
                ],
            ),
        )
    )

    assert published.status == "published"
    assert published.review_status == {"testcases": "confirmed"}
    assert (workspace / "published/testcases/current.md").is_file()


def test_resume_is_separate_from_human_review(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    _create(harness)
    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test login"))

    with pytest.raises(ValueError, match="不可恢复"):
        harness.resume_run(ResumeRunCommand(workspace_id="demo", run_id=snapshot.run_id))


def test_run_lookup_is_workspace_qualified(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    _create(harness, "one")
    _create(harness, "two")
    snapshot = harness.start_run(StartRunCommand(workspace_id="one", goal="test login"))

    with pytest.raises(FileNotFoundError):
        harness.get_run(RunRef(workspace_id="two", run_id=snapshot.run_id))


def test_v1_workspace_is_explicitly_rejected(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    workspace = tmp_path / "workspaces/legacy"
    workspace.mkdir(parents=True)
    (workspace / "workspace.yml").write_text(
        "schema_version: agentic-qa.harness.workspace.v1\nid: legacy\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="v1 is not supported"):
        harness.start_run(StartRunCommand(workspace_id="legacy", goal="test"))


def test_stream_run_emits_a_terminal_snapshot_event(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    _create(harness)

    events = list(harness.stream_run(StartRunCommand(workspace_id="demo", goal="test login")))

    assert events
    snapshot = harness.get_run(RunRef(workspace_id="demo", run_id=events[-1].run_id))
    assert snapshot.status == "needs_human_review"


def test_policy_actions_are_audited(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    workspace = harness.create_workspace(
        CreateWorkspaceCommand(
            workspace_id="demo",
            quality_policies=["city-opening-rewards"],
        )
    )
    (workspace / "sources/rules.md").write_text(
        "正式配置：第1场，新玩家单价10元，老玩家单价5元，预算底标100元，最低核销3人。",
        encoding="utf-8",
    )

    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="核对奖励配置"))
    events = [
        json.loads(line)
        for line in (workspace / f"runs/{snapshot.run_id}/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    policy_events = [item for item in events if item["type"] == "artifact_quality_evaluated"]
    assert policy_events
    city_event = policy_events[0]
    assert city_event["data"]["policy_versions"]["city-opening-rewards"] == "2.0.0"
    assert city_event["data"]["assessment_key"].startswith("sha256:")
    assert city_event["data"]["source_bundle_hash"].startswith("sha256:")


def test_source_blocker_prevents_approve_without_changing_run_state(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    workspace = _create(harness)
    (workspace / "sources/rules.md").write_text("# 奖励配置\n", encoding="utf-8")
    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test login"))
    candidate = snapshot.candidates[0]

    with pytest.raises(PermissionError, match="未通过质量门"):
        harness.review_run(
            ReviewRunCommand(
                workspace_id="demo",
                run_id=snapshot.run_id,
                decision=ReviewDecision(
                    intent="approve",
                    target_artifact="testcases",
                    reason="attempt invalid approval",
                    reviewed_by="qa_owner",
                    versions=[candidate.version_ref(ArtifactVariant.RAW)],
                ),
            )
        )

    current = harness.get_run(RunRef(workspace_id="demo", run_id=snapshot.run_id))
    assert current.status == "needs_human_review"
    assert current.review_status == {"testcases": "needs_human_review"}


def test_promote_rechecks_selected_content_hash(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    _create(harness)
    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test login"))
    candidate = snapshot.candidates[0]
    (tmp_path / candidate.path).write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="hash"):
        harness.review_run(
            ReviewRunCommand(
                workspace_id="demo",
                run_id=snapshot.run_id,
                decision=ReviewDecision(
                    intent="approve",
                    target_artifact="testcases",
                    reason="attempt tampered publish",
                    reviewed_by="qa_owner",
                    versions=[candidate.version_ref(ArtifactVariant.RAW)],
                ),
            )
        )

    current = harness.get_run(RunRef(workspace_id="demo", run_id=snapshot.run_id))
    assert current.status == "needs_human_review"
    assert not (tmp_path / "workspaces/demo/published/testcases/current.md").exists()


def test_hold_writes_review_record_event_and_snapshot(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    workspace = _create(harness)
    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test hold"))

    held = harness.review_run(
        ReviewRunCommand(
            workspace_id="demo",
            run_id=snapshot.run_id,
            decision=ReviewDecision(
                intent="hold",
                target_artifact="testcases",
                reason="等待产品确认",
                reviewed_by="qa_owner",
            ),
        )
    )

    assert held.status == "on_hold"
    assert held.review_status["testcases"] == "on_hold"
    record = json.loads(
        (workspace / f"reviews/{snapshot.run_id}/testcases.review.json").read_text(encoding="utf-8")
    )
    assert record["status"] == "on_hold"
    assert record["decision"]["reviewed_by"] == "qa_owner"
    assert "review_held" in (workspace / f"runs/{snapshot.run_id}/events.jsonl").read_text(
        encoding="utf-8"
    )


def test_artifact_diff_query_has_no_review_side_effects(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    workspace = _create(harness)
    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test diff"))
    before = (workspace / f"runs/{snapshot.run_id}/state.json").read_bytes()
    review_root = workspace / f"reviews/{snapshot.run_id}"

    result = harness.get_artifact_diff(
        GetArtifactDiffQuery(
            workspace_id="demo",
            run_id=snapshot.run_id,
            artifact="testcases",
            before=ArtifactDiffEndpoint.RAW,
            after=ArtifactDiffEndpoint.NORMALIZED,
        )
    )

    assert result.before_sha256 != result.after_sha256
    assert not list(review_root.glob("*.review.json"))
    assert (workspace / f"runs/{snapshot.run_id}/state.json").read_bytes() == before
