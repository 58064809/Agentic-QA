from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import Harness, PlanTask, QAPlan, ReviewDecision, TaskRequest
from harness.budget import BudgetLimits
from harness.engine import AgentOutput, build_default_plan, default_recorded_artifact
from harness.evals import recorded_model_gateway
from harness.model import CallableModelGateway


def _harness(path: Path) -> Harness:
    return Harness(path, model_gateway=recorded_model_gateway())


def test_missing_model_fails_before_creating_a_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AGENTIC_QA_MODEL", raising=False)
    monkeypatch.delenv("AGENTIC_QA_MODEL_FLASH", raising=False)
    monkeypatch.delenv("AGENTIC_QA_MODEL_PRO", raising=False)
    monkeypatch.delenv("AGENTIC_QA_MODEL_API_KEY_ENV", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    harness = Harness(tmp_path)
    workspace = harness.init_workspace("demo")
    with pytest.raises(RuntimeError, match="未配置模型"):
        harness.run(TaskRequest(workspace="demo", goal="test"))
    assert not list((workspace / "runs").iterdir())


def test_run_review_and_deterministic_promote(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.init_workspace("demo")
    snapshot = harness.run(
        TaskRequest(
            workspace="demo",
            goal="验证登录和退出",
            expected_artifacts=["testcases", "requirement_analysis"],
        )
    )

    assert snapshot.status == "needs_human_review"
    assert any(
        route["tier"] == "pro" and route["purpose"] == "expert:risk_strategist"
        for route in snapshot.model_routes
    )
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
    harness = _harness(tmp_path)
    harness.init_workspace("demo")
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test login"))
    run = tmp_path / "workspaces/demo/runs" / snapshot.run_id
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    delegated = [event for event in events if event["type"] == "tasks_delegated"]
    assert delegated[0]["data"]["task_ids"] == ["analyze_requirements", "analyze_risks"]
    assert (run / "checkpoints/graph.sqlite").is_file()


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
    with pytest.raises(PermissionError, match="不可发布"):
        harness.resume(
            snapshot.run_id,
            ReviewDecision(intent="approve", reason="must not publish partial"),
        )


def test_candidate_is_never_overwritten(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
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
    harness = _harness(tmp_path)
    harness.init_workspace("demo")
    events = list(harness.stream(TaskRequest(workspace="demo", goal="test login")))
    assert events[-1].type == "review_required"
    snapshot = harness.inspect(events[-1].run_id)
    assert snapshot.status == "needs_human_review"


def test_recover_retries_same_langgraph_thread_after_planner_crash(tmp_path: Path) -> None:
    failures = 1

    def respond(*, prompt: str, response_model: type, **_kwargs):
        nonlocal failures
        if response_model.__name__ == "QAPlan":
            if failures:
                failures -= 1
                raise RuntimeError("simulated planner crash")
            request = TaskRequest.model_validate_json(prompt.splitlines()[-1])
            return build_default_plan(request).model_dump(mode="json")
        context = json.loads(prompt)
        return AgentOutput(
            summary="recorded",
            artifacts={
                artifact: default_recorded_artifact(artifact, context["goal"])
                for artifact in context["task"]["expected_outputs"]
                if artifact == "testcases"
            },
            evidence=["user_goal"],
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    harness.init_workspace("demo")
    failed = harness.run(TaskRequest(workspace="demo", goal="test login"))
    assert failed.status == "recoverable"

    recovered = harness.resume(failed.run_id)
    assert recovered.status == "needs_human_review"
    assert recovered.run_id == failed.run_id
    assert (tmp_path / f"workspaces/demo/runs/{failed.run_id}/checkpoints/graph.sqlite").is_file()


def test_agent_tool_request_is_executed_and_recorded(tmp_path: Path) -> None:
    def respond(*, prompt: str, response_model: type, **_kwargs):
        if response_model.__name__ == "QAPlan":
            request = TaskRequest.model_validate_json(prompt.splitlines()[-1])
            return build_default_plan(request).model_dump(mode="json")
        context = json.loads(prompt)
        if not context["tool_results"]:
            return AgentOutput(
                summary="need source",
                tool_requests=[
                    {
                        "tool": "workspace.read",
                        "arguments": {"path": "sources/requirement.md"},
                    }
                ],
            )
        return AgentOutput(
            summary="source analyzed",
            artifacts={
                "requirement_analysis": default_recorded_artifact(
                    "requirement_analysis", context["goal"]
                )
            },
            evidence=["sources/requirement.md"],
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    workspace = harness.init_workspace("demo")
    (workspace / "sources/requirement.md").write_text("登录必须校验密码", encoding="utf-8")
    snapshot = harness.run(
        TaskRequest(
            workspace="demo",
            goal="分析登录需求",
            expected_artifacts=["requirement_analysis"],
        )
    )

    assert snapshot.status == "needs_human_review"
    assert snapshot.budget.tool_calls == 1
    assert snapshot.tool_calls[0]["tool"] == "workspace.read"


def test_invalid_artifact_is_repaired_before_candidate_write(tmp_path: Path) -> None:
    feedback_seen: list[list[dict[str, str]]] = []
    valid = default_recorded_artifact("testcases", "test login")
    reversed_headers = [
        "待确认项",
        "断言/证据",
        "预期结果",
        "测试步骤",
        "测试数据",
        "前置条件",
        "优先级",
        "测试类型",
        "标题",
        "需求/规则来源",
        "用例ID",
    ]
    invalid = "\n".join(
        [
            "| " + " | ".join(reversed_headers) + " |",
            "|" + "|".join(["---"] * 11) + "|",
            "| " + " | ".join(["value"] * 11) + " |",
        ]
    )

    def respond(*, prompt: str, response_model: type, **_kwargs):
        if response_model.__name__ == "QAPlan":
            return QAPlan(
                tasks=[
                    PlanTask(
                        id="produce_testcases",
                        objective="produce testcases",
                        agent="test_designer",
                        expected_outputs=["testcases"],
                    )
                ]
            )
        context = json.loads(prompt)
        feedback_seen.append(context["validation_feedback"])
        return AgentOutput(
            summary="candidate",
            artifacts={"testcases": valid if context["validation_feedback"] else invalid},
            evidence=["user_goal"],
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    harness.init_workspace("demo")
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test login"))

    assert snapshot.status == "needs_human_review"
    assert feedback_seen[0] == []
    assert "exact ordered 11-column" in feedback_seen[1][0]["error"]
    assert snapshot.budget.model_calls == 3
    candidate = tmp_path / snapshot.candidates[0].path
    assert candidate.read_text(encoding="utf-8") == valid
    events = [
        json.loads(line)
        for line in (tmp_path / "workspaces/demo/runs" / snapshot.run_id / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["type"] for event in events].count("artifact_validation_failed") == 1


def test_artifact_repair_stops_after_three_attempts(tmp_path: Path) -> None:
    invalid = "# Testcases\n\nmissing required table"

    def respond(*, response_model: type, **_kwargs):
        if response_model.__name__ == "QAPlan":
            return QAPlan(
                tasks=[
                    PlanTask(
                        id="produce_testcases",
                        objective="produce testcases",
                        agent="test_designer",
                        expected_outputs=["testcases"],
                    )
                ]
            )
        return AgentOutput(
            summary="still invalid",
            artifacts={"testcases": invalid},
            evidence=["user_goal"],
        )

    harness = Harness(
        tmp_path,
        model_gateway=CallableModelGateway(respond),
        budget_limits=BudgetLimits(max_replans=0),
    )
    harness.init_workspace("demo")
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test login"))

    assert snapshot.status == "partial"
    assert snapshot.budget.model_calls == 4
    assert snapshot.candidates[0].status == "partial"
    events = [
        json.loads(line)
        for line in (tmp_path / "workspaces/demo/runs" / snapshot.run_id / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["type"] for event in events].count("artifact_validation_failed") == 3
