from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

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
from harness.infrastructure.llm.gateway import CallableModelGateway
from harness.infrastructure.workflow.engine import default_recorded_testcase_set
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
        "\n".join(
            [
                "# 领取奖励条件",
                "",
                "- 报名",
                "- 核销",
                "- 进入获奖名单",
                "- 发布趣看动态",
                "- 带 #今天一起开局 话题",
                "- @交子立方官方号",
            ]
        ),
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
    assert city_event["data"]["policy_versions"]["city-opening-rewards"] == "1.0.0"
    assert city_event["data"]["reviewer_roles"] == ["independent_deterministic_reviewer"]
    assert city_event["data"]["assessment_key"].startswith("sha256:")
    assert city_event["data"]["source_bundle_hash"].startswith("sha256:")
    revision_events = [
        item for item in events if item["type"] == "artifact_quality_revision_requested"
    ]
    assert not revision_events
    assert snapshot.status == "partial"
    generation_report = json.loads(
        (tmp_path / snapshot.candidates[0].generation_report_path).read_text(encoding="utf-8")
    )
    quality_report = json.loads(
        (tmp_path / snapshot.candidates[0].quality_report_path).read_text(encoding="utf-8")
    )
    assert {
        strategy["reviewer_role"]
        for variant in quality_report["variants"]
        for strategy in variant["strategies"]
    } == {"independent_deterministic_reviewer"}
    assert generation_report["llm_used"] is True
    assert generation_report["quality_revisions"] == 0
    assert generation_report["model_calls"][-1]["outcome"] == "quality_rejected"


def test_quality_feedback_includes_rejected_draft_and_repairs_candidate(
    tmp_path: Path,
) -> None:
    recorded = recorded_model_gateway()
    test_designer_calls = 0

    def respond(
        *,
        prompt: str,
        response_model: type,
        **kwargs: Any,
    ) -> Any:
        nonlocal test_designer_calls
        context = json.loads(prompt) if response_model.__name__ == "AgentOutput" else {}
        if context.get("task", {}).get("expected_outputs") == ["testcases"]:
            test_designer_calls += 1
            if test_designer_calls == 1:
                initial = default_recorded_testcase_set("test login").model_dump(mode="json")
                initial["coverage"][0]["rationale"] = "待补充"
                return {
                    "summary": "first draft",
                    "artifacts": {},
                    "testcase_set": initial,
                    "evidence": ["user_goal"],
                    "pending": [],
                    "tool_requests": [],
                }
            feedback = context["validation_feedback"][-1]
            assert "testcases" in feedback["previous_artifacts"]
        return recorded._callback(  # noqa: SLF001 - recorded gateway is a test fixture
            prompt=prompt,
            response_model=response_model,
            **kwargs,
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    _create(harness)

    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test login"))

    assert snapshot.status == "needs_human_review"
    assert test_designer_calls == 2
    generation_report = json.loads(
        (tmp_path / snapshot.candidates[0].generation_report_path).read_text(encoding="utf-8")
    )
    assert generation_report["quality_revisions"] == 1
    assert [item["outcome"] for item in generation_report["model_calls"]] == [
        "quality_rejected",
        "quality_accepted",
    ]


def test_requirement_sources_are_extracted_per_file_with_generation_provenance(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    workspace = _create(harness)
    (workspace / "sources/a.md").write_text("# A\n\n规则A。", encoding="utf-8")
    (workspace / "sources/b.md").write_text("# B\n\n规则B。", encoding="utf-8")

    snapshot = harness.start_run(
        StartRunCommand(
            workspace_id="demo",
            goal="extract rules and design tests",
            expected_artifacts=["requirement_analysis", "testcases"],
        )
    )

    requirement = next(
        candidate
        for candidate in snapshot.candidates
        if candidate.artifact == "requirement_analysis"
    )
    report = json.loads((tmp_path / requirement.generation_report_path).read_text(encoding="utf-8"))
    fragment_calls = [
        call
        for call in report["model_calls"]
        if call["prompt_template_version"] == "requirement-fragment-v1"
    ]
    assert len(fragment_calls) == 2
    assert {
        selection["source"] for call in fragment_calls for selection in call["source_selection"]
    } == {"sources/a.md", "sources/b.md"}
    assert all(call["raw_response_sha256"] for call in report["model_calls"])
    assert all(call["latency_ms"] >= 0 for call in report["model_calls"])
    assert all(call["finish_reason"] == "recorded" for call in report["model_calls"])
    assert all(call["input_context_characters"] > 0 for call in report["model_calls"])
    assert all(
        selection["raw_sha256"] for call in fragment_calls for selection in call["source_selection"]
    )


def test_test_designer_executes_bounded_rule_batches_and_merges_them(
    tmp_path: Path,
) -> None:
    recorded = recorded_model_gateway()
    batch_rule_ids: list[list[str]] = []

    def respond(
        *,
        prompt: str,
        response_model: type,
        **kwargs: Any,
    ) -> Any:
        context = json.loads(prompt) if response_model.__name__ == "AgentOutput" else {}
        payload = recorded._callback(  # noqa: SLF001 - recorded gateway is a test fixture
            prompt=prompt,
            response_model=response_model,
            **kwargs,
        )
        if context.get("rule_batch"):
            batch_rule_ids.append(context["rule_batch"]["rule_ids"])
        if context.get("task", {}).get("agent") == "requirement_analyst" and context.get(
            "source_fragments"
        ):
            catalog = payload["requirement_catalog"]
            template = catalog["rules"][0]
            catalog["rules"] = [
                template,
                *[
                    {
                        **deepcopy(template),
                        "rule_id": f"BATCH-{index:03d}",
                        "title": f"batch rule {index}",
                    }
                    for index in range(1, 7)
                ],
            ]
        return payload

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    workspace = _create(harness)
    (workspace / "sources/rules.md").write_text(
        "# rules\n\nSeven independent business rules.",
        encoding="utf-8",
    )

    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="design seven rules"))

    assert snapshot.status == "needs_human_review", (
        snapshot.errors,
        batch_rule_ids,
    )
    assert [len(rule_ids) for rule_ids in batch_rule_ids] == [5, 2]
    assert {rule_id for rule_ids in batch_rule_ids for rule_id in rule_ids} >= {
        f"BATCH-{index:03d}" for index in range(1, 7)
    }
    candidate = next(item for item in snapshot.candidates if item.artifact == "testcases")
    raw_version = next(
        version for version in candidate.versions if version.variant == ArtifactVariant.RAW
    )
    raw = (tmp_path / raw_version.path).read_text(encoding="utf-8")
    assert all(f"BATCH-{index:03d}" in raw for index in range(1, 7))
    report = json.loads((tmp_path / candidate.generation_report_path).read_text(encoding="utf-8"))
    batch_calls = [
        call
        for call in report["model_calls"]
        if call["prompt_template_version"] == "testcase-rule-batch-v1"
    ]
    assert len(batch_calls) == 2
    assert all(call["source_selection"] for call in batch_calls)
    assert all(
        selection["raw_sha256"] for call in batch_calls for selection in call["source_selection"]
    )


def test_testcase_rule_batch_can_retrieve_source_evidence_on_demand(
    tmp_path: Path,
) -> None:
    recorded = recorded_model_gateway()
    requested = False
    consumed_retrieval = False

    def respond(
        *,
        prompt: str,
        response_model: type,
        **kwargs: Any,
    ) -> Any:
        nonlocal requested, consumed_retrieval
        context = json.loads(prompt) if response_model.__name__ == "AgentOutput" else {}
        if context.get("rule_batch") and not requested:
            requested = True
            return {
                "summary": "need source evidence",
                "artifacts": {},
                "evidence": [],
                "pending": [],
                "tool_requests": [
                    {
                        "tool": "rag.retrieve",
                        "arguments": {"query": "login lock threshold", "max_chunks": 2},
                    }
                ],
            }
        if context.get("rule_batch") and context.get("tool_results"):
            consumed_retrieval = True
            assert context["source_prefetched"] is False
        return recorded._callback(  # noqa: SLF001 - recorded gateway is a test fixture
            prompt=prompt,
            response_model=response_model,
            **kwargs,
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    workspace = _create(harness)
    (workspace / "sources/login.md").write_text(
        "# Login\n\nLock the account after five consecutive failures.",
        encoding="utf-8",
    )

    snapshot = harness.start_run(
        StartRunCommand(workspace_id="demo", goal="design login lock tests")
    )

    assert snapshot.status == "needs_human_review", snapshot.errors
    assert requested
    assert consumed_retrieval
    candidate = next(item for item in snapshot.candidates if item.artifact == "testcases")
    report = json.loads((tmp_path / candidate.generation_report_path).read_text(encoding="utf-8"))
    retrieved = [
        selection
        for call in report["model_calls"]
        for selection in call["source_selection"]
        if selection.get("chunk_id")
    ]
    assert retrieved
    assert all(selection["raw_sha256"] for selection in retrieved)


def test_generation_report_marks_artifact_contract_rejection(tmp_path: Path) -> None:
    recorded = recorded_model_gateway()
    rejected = False

    def respond(
        *,
        prompt: str,
        response_model: type,
        **kwargs: Any,
    ) -> Any:
        nonlocal rejected
        context = json.loads(prompt) if response_model.__name__ == "AgentOutput" else {}
        if not rejected and context.get("task", {}).get("agent") == "test_designer":
            rejected = True
            return {
                "summary": "legacy markdown output",
                "artifacts": {"testcases": "# invalid direct markdown"},
                "evidence": ["user_goal"],
                "pending": [],
                "tool_requests": [],
            }
        return recorded._callback(  # noqa: SLF001 - recorded gateway is a test fixture
            prompt=prompt,
            response_model=response_model,
            **kwargs,
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    _create(harness)
    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test login"))

    candidate = next(item for item in snapshot.candidates if item.artifact == "testcases")
    report = json.loads((tmp_path / candidate.generation_report_path).read_text(encoding="utf-8"))
    assert report["model_calls"][0]["outcome"] == "artifact_validation_rejected"
    assert report["model_calls"][0]["failure_stage"] == "testcase_rule_batch_contract"
    assert report["model_calls"][0]["artifact_validation_retries"] == 1


def test_source_blocker_marks_partial_and_prevents_approve(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    workspace = _create(harness)
    (workspace / "sources/rules.md").write_text("# 奖励配置\n", encoding="utf-8")
    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test login"))
    candidate = snapshot.candidates[0]

    assert snapshot.status == "partial"
    assert snapshot.review_status == {"testcases": "needs_revision"}

    with pytest.raises(PermissionError, match="partial candidate"):
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
    assert current.status == "partial"
    assert current.review_status == {"testcases": "needs_revision"}


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
