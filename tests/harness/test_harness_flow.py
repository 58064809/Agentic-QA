from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness import Harness, PlanTask, QAPlan, ReviewDecision, TaskRequest
from harness.budget import BudgetLimits
from harness.engine import (
    AgentOutput,
    _quality_check,
    build_default_plan,
    default_recorded_artifact,
)
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


def test_review_decision_requires_explicit_reviewer_identity() -> None:
    with pytest.raises(ValidationError, match="reviewed_by"):
        ReviewDecision(intent="approve", reason="reviewed")


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
            ReviewDecision(intent="approve", reason="reviewed", reviewed_by="qa_owner"),
        )

    published = harness.resume(
        snapshot.run_id,
        ReviewDecision(
            intent="approve",
            target_artifact="all",
            reason="reviewed",
            reviewed_by="qa_owner",
        ),
    )
    assert published.status == "published"
    assert (tmp_path / "workspaces/demo/published/testcases/current.md").is_file()
    assert harness.inspect(snapshot.run_id).review_status["testcases"] == "confirmed"


def test_revision_updates_each_target_review_status(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.init_workspace("demo")
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test login"))

    revised = harness.resume(
        snapshot.run_id,
        ReviewDecision(
            intent="revise",
            target_artifact="all",
            reason="coverage incomplete",
            revision_request="add missing cases",
            reviewed_by="qa_owner",
        ),
    )

    assert revised.status == "needs_revision"
    assert revised.review_status == {"testcases": "needs_revision"}


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
            ReviewDecision(
                intent="approve",
                reason="must not publish partial",
                reviewed_by="qa_owner",
            ),
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


def test_planner_repairs_semantically_invalid_plan_in_same_run(tmp_path: Path) -> None:
    plans = 0

    def respond(*, prompt: str, response_model: type, **_kwargs):
        nonlocal plans
        if response_model.__name__ == "QAPlan":
            plans += 1
            request = TaskRequest.model_validate_json(prompt.splitlines()[-1])
            if plans == 1:
                return QAPlan(
                    tasks=[
                        PlanTask(
                            id="analyze_risks",
                            objective="analyze risks",
                            agent="risk_strategist",
                            expected_outputs=["risk_context"],
                        )
                    ]
                )
            assert "QAPlan 未覆盖期望产物" in prompt
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
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test login"))

    assert snapshot.status == "needs_human_review"
    assert plans == 2
    assert snapshot.budget.model_calls == 5
    events = [
        json.loads(line)
        for line in (tmp_path / "workspaces/demo/runs" / snapshot.run_id / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["type"] for event in events].count("plan_validation_failed") == 1


def test_planner_repairs_public_artifact_assigned_to_wrong_agent(tmp_path: Path) -> None:
    plans = 0

    def respond(*, prompt: str, response_model: type, **_kwargs):
        nonlocal plans
        if response_model.__name__ == "QAPlan":
            plans += 1
            agent = "qa_supervisor" if plans == 1 else "requirement_analyst"
            if plans == 2:
                assert "requirement_analysis 必须由 requirement_analyst 生成" in prompt
            return QAPlan(
                tasks=[
                    PlanTask(
                        id="produce-requirement-analysis",
                        objective="produce requirement analysis",
                        agent=agent,
                        expected_outputs=["requirement_analysis"],
                    )
                ]
            )
        context = json.loads(prompt)
        return AgentOutput(
            summary="requirement analysis",
            artifacts={
                "requirement_analysis": default_recorded_artifact(
                    "requirement_analysis", context["goal"]
                )
            },
            evidence=["user_goal"],
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    harness.init_workspace("demo")
    snapshot = harness.run(
        TaskRequest(
            workspace="demo",
            goal="analyze requirement",
            expected_artifacts=["requirement_analysis"],
        )
    )

    assert snapshot.status == "needs_human_review"
    assert plans == 2
    assert snapshot.plan is not None
    assert snapshot.plan.tasks[0].agent == "requirement_analyst"


def test_agent_tool_request_is_executed_and_recorded(tmp_path: Path) -> None:
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
            artifacts={"testcases": default_recorded_artifact("testcases", context["goal"])},
            evidence=["sources/requirement.md"],
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    workspace = harness.init_workspace("demo")
    (workspace / "sources/requirement.md").write_text("登录必须校验密码", encoding="utf-8")
    snapshot = harness.run(
        TaskRequest(
            workspace="demo",
            goal="设计登录用例",
            expected_artifacts=["testcases"],
        )
    )

    assert snapshot.status == "needs_human_review"
    assert snapshot.budget.tool_calls == 1
    assert snapshot.tool_calls[0]["tool"] == "workspace.read"


def test_source_dependent_agent_receives_prefetched_source(tmp_path: Path) -> None:
    expert_contexts: list[dict[str, object]] = []

    def respond(*, prompt: str, response_model: type, **_kwargs):
        if response_model.__name__ == "QAPlan":
            return QAPlan(
                tasks=[
                    PlanTask(
                        id="analyze_requirements",
                        objective="analyze requirement",
                        agent="requirement_analyst",
                        expected_outputs=["requirement_analysis"],
                    )
                ]
            )
        context = json.loads(prompt)
        expert_contexts.append(context)
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
    (workspace / "sources/requirement.md").write_text(
        "登录必须校验密码",
        encoding="utf-8",
    )
    snapshot = harness.run(
        TaskRequest(
            workspace="demo",
            goal="分析登录需求",
            expected_artifacts=["requirement_analysis"],
        )
    )

    assert snapshot.status == "needs_human_review"
    assert len(expert_contexts) == 1
    assert expert_contexts[0]["source_prefetched"] is True
    tool_results = expert_contexts[0]["tool_results"]
    assert isinstance(tool_results, list)
    assert tool_results[0]["result"]["content"] == "登录必须校验密码"
    assert snapshot.budget.tool_calls == 1


def test_invalid_structured_agent_output_is_retried_without_replan(tmp_path: Path) -> None:
    expert_attempts = 0

    def respond(*, prompt: str, response_model: type, **_kwargs):
        nonlocal expert_attempts
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
        expert_attempts += 1
        if expert_attempts == 1:
            raise RuntimeError("model_gateway_error:ValidationError:json_invalid")
        context = json.loads(prompt)
        assert context["validation_feedback"][0]["kind"] == "structured_output"
        return AgentOutput(
            summary="valid retry",
            artifacts={"testcases": default_recorded_artifact("testcases", context["goal"])},
            evidence=["user_goal"],
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    harness.init_workspace("demo")
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test login"))

    assert snapshot.status == "needs_human_review"
    assert expert_attempts == 2
    assert snapshot.budget.model_calls == 3
    assert snapshot.budget.replans == 0
    events = [
        json.loads(line)
        for line in (tmp_path / "workspaces/demo/runs" / snapshot.run_id / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["type"] for event in events].count("model_output_invalid") == 1


def test_partial_preserves_candidate_already_written_before_budget_exhaustion(
    tmp_path: Path,
) -> None:
    def respond(*, prompt: str, response_model: type, **_kwargs):
        if response_model.__name__ == "QAPlan":
            return QAPlan(
                tasks=[
                    PlanTask(
                        id="analyze_requirements",
                        objective="analyze requirement",
                        agent="requirement_analyst",
                        expected_outputs=["requirement_analysis"],
                    ),
                    PlanTask(
                        id="produce_testcases",
                        objective="produce testcases",
                        agent="test_designer",
                        dependencies=["analyze_requirements"],
                        expected_outputs=["testcases"],
                    ),
                ]
            )
        context = json.loads(prompt)
        return AgentOutput(
            summary="requirement",
            artifacts={
                "requirement_analysis": default_recorded_artifact(
                    "requirement_analysis", context["goal"]
                )
            },
            evidence=["user_goal"],
        )

    harness = Harness(
        tmp_path,
        model_gateway=CallableModelGateway(respond),
        budget_limits=BudgetLimits(max_model_calls=2),
    )
    harness.init_workspace("demo")
    snapshot = harness.run(
        TaskRequest(
            workspace="demo",
            goal="test login",
            expected_artifacts=["requirement_analysis", "testcases"],
        )
    )

    assert snapshot.status == "partial"
    candidates = {candidate.artifact: candidate for candidate in snapshot.candidates}
    assert candidates["requirement_analysis"].quality_passed is True
    assert candidates["requirement_analysis"].status == "needs_human_review"
    assert candidates["testcases"].quality_passed is False
    assert candidates["testcases"].status == "partial"


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


def test_source_absent_implementation_observations_are_repaired(tmp_path: Path) -> None:
    valid = default_recorded_artifact("testcases", "test login")
    attempts = 0

    def respond(*, prompt: str, response_model: type, **_kwargs):
        nonlocal attempts
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
        attempts += 1
        context = json.loads(prompt)
        if attempts == 2:
            assert "remove implementation observations absent from sources" in str(
                context["validation_feedback"]
            )
        content = valid if attempts == 2 else valid + "\n\n证据来自后台、数据库和日志。"
        return AgentOutput(
            summary="candidate",
            artifacts={"testcases": content},
            evidence=["sources/requirement.md"],
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    workspace = harness.init_workspace("demo")
    (workspace / "sources/requirement.md").write_text(
        "用户登录后可以查看登录结果。",
        encoding="utf-8",
    )
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test login"))

    assert snapshot.status == "needs_human_review"
    assert attempts == 2


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


def test_internal_task_output_is_not_written_as_public_candidate(tmp_path: Path) -> None:
    def respond(*, prompt: str, response_model: type, **_kwargs):
        if response_model.__name__ == "QAPlan":
            return QAPlan(
                tasks=[
                    PlanTask(
                        id="risk_analysis",
                        objective="analyze risks",
                        agent="risk_strategist",
                        expected_outputs=["risk_analysis"],
                    ),
                    PlanTask(
                        id="produce_testcases",
                        objective="produce testcases",
                        agent="test_designer",
                        dependencies=["risk_analysis"],
                        expected_outputs=["testcases"],
                    ),
                ]
            )
        context = json.loads(prompt)
        if context["task"]["agent"] == "risk_strategist":
            return AgentOutput(
                summary="risk context",
                artifacts={"risk_analysis": "High risk: authentication"},
                evidence=["user_goal"],
            )
        return AgentOutput(
            summary="testcases",
            artifacts={"testcases": default_recorded_artifact("testcases", context["goal"])},
            evidence=["risk_analysis"],
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    harness.init_workspace("demo")
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test login"))

    assert snapshot.status == "needs_human_review"
    assert [candidate.artifact for candidate in snapshot.candidates] == ["testcases"]
    assert not (
        tmp_path / f"workspaces/demo/candidates/{snapshot.run_id}/risk_analysis.md"
    ).exists()


def test_testcase_quality_gate_rejects_multiline_markdown_rows() -> None:
    content = "\n".join(
        [
            "| 用例ID | 需求/规则来源 | 标题 | 测试类型 | 优先级 | 前置条件 | 测试数据 | "
            "测试步骤 | 预期结果 | 断言/证据 | 待确认项 |",
            "|" + "|".join(["---"] * 11) + "|",
            "| TC-001 | source | title | 功能 | P1 | ready | data | 1. first",
            "2. second | result | evidence | none |",
            "# 覆盖矩阵",
            "| 规则/风险 | 测试用例 | 映射依据 |",
            "|---|---|---|",
            "| rule | TC-001 | source |",
        ]
    )

    with pytest.raises(ValueError, match="multiline"):
        _quality_check("testcases", content)


def test_testcase_quality_gate_accepts_semantic_coverage_headers() -> None:
    content = "\n".join(
        [
            "| 用例ID | 需求/规则来源 | 标题 | 测试类型 | 优先级 | 前置条件 | 测试数据 | "
            "测试步骤 | 预期结果 | 断言/证据 | 待确认项 |",
            "|" + "|".join(["---"] * 11) + "|",
            "| TC-001 | source | title | 功能 | P1 | ready | data | step | result | "
            "evidence | none |",
            "# 覆盖矩阵",
            "| 覆盖规则/风险点 | 关联用例ID | 验证说明 |",
            "|---|---|---|",
            "| rule | TC-001 | source |",
        ]
    )

    _quality_check("testcases", content)


def test_requirement_quality_gate_rejects_embedded_testcases() -> None:
    content = "\n".join(
        [
            "# Requirement Analysis",
            "## 来源",
            "- source",
            "## 已确认规则",
            "- rule",
            "## 待确认项",
            "- pending",
            "# 测试用例",
            "| 用例ID |",
        ]
    )

    with pytest.raises(ValueError, match="must not embed testcases"):
        _quality_check("requirement_analysis", content)


def test_requirement_quality_gate_preserves_approximate_suggestion_status() -> None:
    content = "\n".join(
        [
            "# Requirement Analysis",
            "## 来源",
            "- source",
            "## 已确认规则",
            "- 获奖人数比例固定为50%，按四舍五入计算。",
            "## 待确认项",
            "- none",
        ]
    )
    source = "每场获奖人数按约 50% 测算。开发计算建议：人数 × 50%。"

    with pytest.raises(ValueError, match="non-final suggestions"):
        _quality_check("requirement_analysis", content, source_corpus=source)
