from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness import Harness, PlanTask, QAPlan, ReviewDecision, TaskRequest
from harness.budget import BudgetLimits
from harness.engine import (
    AgentOutput,
    _deterministically_enrich_artifact,
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
    assert snapshot.plan is not None
    assert snapshot.plan.tasks[0].agent == "requirement_analyst"
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


def test_agent_repairs_undelegated_artifact_without_supervisor_replan(tmp_path: Path) -> None:
    outputs = 0

    def respond(*, prompt: str, response_model: type, **_kwargs):
        nonlocal outputs
        if response_model.__name__ == "QAPlan":
            return QAPlan(
                tasks=[
                    PlanTask(
                        id="produce-testcases",
                        objective="produce testcases",
                        agent="test_designer",
                        expected_outputs=["testcases"],
                    )
                ]
            )
        outputs += 1
        context = json.loads(prompt)
        if outputs == 1:
            return AgentOutput(
                summary="split output",
                artifacts={
                    "testcases": default_recorded_artifact("testcases", "test login"),
                    "coverage_matrix": "| rule | TC-001 | source |",
                },
            )
        assert "undelegated artifacts" in json.dumps(
            context["validation_feedback"], ensure_ascii=False
        )
        return AgentOutput(
            summary="repaired output",
            artifacts={"testcases": default_recorded_artifact("testcases", "test login")},
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    harness.init_workspace("demo")
    snapshot = harness.run(TaskRequest(workspace="demo", goal="test login"))

    assert snapshot.status == "needs_human_review"
    assert outputs == 2
    assert snapshot.plan.revision == 0
    events = [
        json.loads(line)
        for line in (tmp_path / "workspaces/demo/runs" / snapshot.run_id / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["type"] for event in events].count("artifact_validation_failed") == 1


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


def test_source_absent_implementation_prose_is_removed_without_model_retry(
    tmp_path: Path,
) -> None:
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
        content = valid + "\n\n证据来自后台、数据库和日志。"
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
    assert attempts == 1
    candidate = tmp_path / snapshot.candidates[0].path
    candidate_text = candidate.read_text(encoding="utf-8")
    assert "后台" not in candidate_text
    assert "数据库" not in candidate_text
    assert "日志" not in candidate_text
    assert "具体实现假设已移除" in candidate_text


def test_artifact_repair_stops_after_five_attempts(tmp_path: Path) -> None:
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
    assert snapshot.budget.model_calls == 6
    assert snapshot.candidates[0].status == "partial"
    events = [
        json.loads(line)
        for line in (tmp_path / "workspaces/demo/runs" / snapshot.run_id / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["type"] for event in events].count("artifact_validation_failed") == 5


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

    with pytest.raises(ValueError, match=r"physical lines: \[4\]"):
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


def _testcase_artifact(row: list[str]) -> str:
    assert len(row) == 11
    return "\n".join(
        [
            "| 用例ID | 需求/规则来源 | 标题 | 测试类型 | 优先级 | 前置条件 | 测试数据 | "
            "测试步骤 | 预期结果 | 断言/证据 | 待确认项 |",
            "|" + "|".join(["---"] * 11) + "|",
            "| " + " | ".join(row) + " |",
            "## 覆盖矩阵",
            "| 规则/风险 | 测试用例 | 映射依据 |",
            "|---|---|---|",
            f"| source rule | {row[0]} | source mapping |",
        ]
    )


def test_source_config_deterministically_enriches_testcases() -> None:
    content = default_recorded_artifact("testcases", "核对正式配置")
    source = "\n".join(
        [
            "| 场次 | 新客户奖励 | 老客户奖励 | 预算底标 | 最低核销人数 |",
            "|---:|---:|---:|---:|---:|",
            "| 1 | 20元 | 0元 | 300元 | 10人 |",
            "| 2 | 25元 | 16元 | 240元 | 10人 |",
        ]
    )

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )

    assert metadata == {
        "artifact": "testcases",
        "rules": ["source_formal_reward_config"],
        "source_rows": 2,
        "generated_case_id": "TC-CONFIG-SOURCE",
        "normalized_case_ids": [],
    }
    assert "第1场：新玩家20元、老玩家0元、预算底标300元、最低核销10人" in enriched
    assert "| 正式奖励配置逐场字段 | TC-CONFIG-SOURCE |" in enriched
    _quality_check("testcases", enriched, source_corpus=source)

    unchanged, second_metadata = _deterministically_enrich_artifact(
        "testcases",
        enriched,
        source_corpus=source,
    )
    assert unchanged == enriched
    assert second_metadata is None


def test_source_uncertainties_are_deterministically_normalized() -> None:
    rows = [
        [
            "TC-LOW-001",
            "source",
            "5人参与奖励核对",
            "功能",
            "P1",
            "本场核销=5",
            "5人",
            "执行奖励流程",
            "5人均获得奖励",
            "奖励结果",
            "无",
        ],
        [
            "TC-CALC-001",
            "source",
            "10人按50%获奖",
            "规则",
            "P1",
            "核销人数10人",
            "10×50%=5",
            "计算获奖人数",
            "固定有5人获奖",
            "结果为5人",
            "无",
        ],
        [
            "TC-CONTENT-001",
            "source",
            "灌水内容真实性校验",
            "规则",
            "P1",
            "存在灌水内容",
            "灌水文本",
            "提交内容",
            "系统判定内容无效且不计入",
            "计数不增加",
            "无",
        ],
        [
            "TC-COMBAT-001",
            "source",
            "对抗活动展示",
            "规则",
            "P1",
            "满足对抗类三条件",
            "两队结果",
            "查看展示结果",
            "显示胜队和排名",
            "页面显示胜队",
            "无",
        ],
        [
            "TC-GROWTH-001",
            "source",
            "成长金最高档",
            "规则",
            "P1",
            "同时满足多档条件",
            "成长金档位",
            "核对结果",
            "最高档成长金到账",
            "到账记录",
            "无",
        ],
    ]
    content = _testcase_artifact(rows[0])
    extra_rows = "\n".join("| " + " | ".join(row) + " |" for row in rows[1:])
    content = content.replace("## 覆盖矩阵", f"{extra_rows}\n## 覆盖矩阵")
    source = "\n".join(
        [
            "最低核销人数为10人。",
            "每场获奖人数约 50%，开发计算建议为人数乘以50%。",
            "内容“真实有效”，具体判定方式待确认。",
            "前端展示建议：可以展示为胜队和排名。",
            "成长金发放时机待确认。",
        ]
    )

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )

    assert metadata == {
        "artifact": "testcases",
        "rules": [
            "block_low_participant_case",
            "block_unconfirmed_content_judgment",
            "condition_approximate_suggestion",
            "condition_combat_display_suggestion",
            "remove_unconfirmed_growth_payout",
        ],
        "source_rows": 0,
        "generated_case_id": None,
        "normalized_case_ids": [
            "TC-CALC-001",
            "TC-COMBAT-001",
            "TC-CONTENT-001",
            "TC-GROWTH-001",
            "TC-LOW-001",
        ],
    }
    assert "| TC-LOW-001 |" in enriched and "| 不执行 | 不可执行：" in enriched
    assert "若采用来源中的当前建议" in enriched
    assert "内容真实性判定方式未确认" in enriched
    assert "来源中的对抗类展示仅为建议" in enriched
    assert "实际发放时机待确认" in enriched
    _quality_check("testcases", enriched, source_corpus=source)
    unchanged, second_metadata = _deterministically_enrich_artifact(
        "testcases",
        enriched,
        source_corpus=source,
    )
    assert unchanged == enriched
    assert second_metadata is None


def test_missing_verification_does_not_match_following_numbered_step() -> None:
    content = _testcase_artifact(
        [
            "TC-NO-VERIFY",
            "source",
            "未完成核销时不满足领取条件",
            "功能",
            "P1",
            "1. 用户已报名<br>2. 活动完成<br>3. 用户未核销",
            "用户未核销",
            "1. 核对条件<br>2. 记录结果",
            "不满足已确认的核销条件",
            "条件核对记录",
            "结果观察点待确认",
        ]
    )
    source = "正式配置的最低核销人数为10人。"

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )

    assert enriched == content
    assert metadata is None
    _quality_check("testcases", content, source_corpus=source)


def test_conflicting_reward_examples_are_replaced_with_source_backed_audit() -> None:
    content = _testcase_artifact(
        [
            "TC-BAD-PRICE",
            "model example",
            "第1场错误金额示例",
            "功能",
            "P0",
            "主理人第1场活动",
            "第1场：新玩家4元、老玩家10元、预算底标20元、最低核销10人",
            "按示意值计算",
            "获得示意金额",
            "示意金额记录",
            "观察点待确认",
        ]
    ).replace(
        "| source rule | TC-BAD-PRICE | source mapping |",
        "| 第1场错误示意 | TC-BAD-PRICE | 第1场新玩家单价4元 |",
    )
    source = "\n".join(
        [
            "| 场次 | 新客户奖励 | 老客户奖励 | 预算底标 | 最低核销人数 |",
            "|---:|---:|---:|---:|---:|",
            "| 1 | 20元 | 0元 | 300元 | 10人 |",
        ]
    )

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )

    assert metadata == {
        "artifact": "testcases",
        "rules": [
            "remove_conflicting_reward_coverage",
            "remove_conflicting_reward_example",
            "source_formal_reward_config",
        ],
        "source_rows": 1,
        "generated_case_id": "TC-CONFIG-SOURCE",
        "normalized_case_ids": ["TC-BAD-PRICE"],
    }
    assert "新玩家4元" not in enriched
    assert "预算底标20元" not in enriched
    assert "单价与底标仅取正式配置快照" in enriched
    assert "以 TC-CONFIG-SOURCE 的正式来源表和来源计算公式为准" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_decimal_reward_prices_without_a_known_stage_are_rejected() -> None:
    content = _testcase_artifact(
        [
            "TC-DECIMAL-PRICE",
            "invented dated config",
            "篮球日期场奖励",
            "功能",
            "P1",
            "活动已完成",
            "新单价14.80元，老单价10.80元，底标2000元",
            "计算奖金池",
            "按日期场配置计算",
            "保留计算结果",
            "无",
        ]
    )
    source = "\n".join(
        [
            "| 场次 | 新客户奖励 | 老客户奖励 | 预算底标 | 最低核销人数 |",
            "|---:|---:|---:|---:|---:|",
            "| 1 | 20元 | 0元 | 300元 | 10人 |",
        ]
    )

    with pytest.raises(ValueError, match="conflict with the formal"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert "remove_conflicting_reward_example" in metadata["rules"]
    assert "14.80" not in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_unsourced_implementation_observations_are_conditioned_in_table_rows() -> None:
    content = _testcase_artifact(
        [
            "TC-OBS-001",
            "source",
            "领取入口核对",
            "功能",
            "P1",
            "后台活动属性已配置奖励",
            "用户满足条件",
            "点击领取按钮",
            "奖励页面显示成功",
            "检查后台日志",
            "无",
        ]
    )
    source = "用户满足全部领取条件后可获得奖励，具体产品入口与观察点待确认。"

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )

    assert metadata == {
        "artifact": "testcases",
        "rules": ["condition_unsourced_implementation_observation"],
        "source_rows": 0,
        "generated_case_id": None,
        "normalized_case_ids": ["TC-OBS-001"],
    }
    for term in ("后台", "日志", "奖励页面", "领取按钮", "活动属性"):
        assert term not in enriched
    assert "若相关产品入口经确认" in enriched
    assert "若相关产品行为经确认" in enriched
    assert "具体产品入口与观察点待确认" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_missing_reward_condition_does_not_invent_ui_or_prompt_observation() -> None:
    content = _testcase_artifact(
        [
            "TC-REWARD-MISSING",
            "城市开局计划 H5 规则.md:318-323",
            "缺少报名条件",
            "功能",
            "P1",
            "用户未报名，其他条件满足",
            "未报名用户",
            "查看奖励列表",
            "界面显示0元并提示需报名",
            "奖励列表不含活动",
            "无",
        ]
    )
    source = "## 领取奖励条件\n用户需同时满足报名、核销、进入获奖名单等六项条件。"

    with pytest.raises(ValueError, match="undefined UI, prompt, list, or amount"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert metadata["rules"] == ["condition_partial_reward_evidence"]
    assert "不满足来源中要求同时成立的全部领取条件" in enriched
    assert "不断言未定义界面、提示或发放记录" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_reward_condition_does_not_cause_award_list_membership() -> None:
    content = _testcase_artifact(
        [
            "TC-REWARD-CAUSE",
            "奖励六条件:318",
            "已报名用户进入获奖名单",
            "功能",
            "P1",
            "用户已报名",
            "报名用户",
            "核对报名状态",
            "用户出现在获奖名单中",
            "获奖名单包含用户",
            "名单生成规则待确认",
        ]
    )
    source = "## 领取奖励条件\n用户需同时满足报名、核销、进入获奖名单等六项条件。"

    with pytest.raises(ValueError, match="undefined UI, prompt, list, or amount"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, _ = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert "仅确认当前来源条件满足" in enriched
    assert "获奖名单包含用户" not in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_complete_reward_conditions_do_not_assert_unconfirmed_payout() -> None:
    content = _testcase_artifact(
        [
            "TC-REWARD-PAYOUT",
            "城市开局计划 H5 规则 §01 领取条件1-6",
            "六项条件全部满足",
            "功能",
            "P1",
            "已报名、核销并进入获奖名单",
            "趣看动态带#今天一起开局并@交子立方官方号",
            "核对六项条件后发放奖励",
            "奖励发放成功",
            "观察奖励到账通知和可领奖状态",
            "自动或手动发放待确认",
        ]
    )
    source = "## 领取奖励条件\n318-323 六项条件；奖励自动发放还是手动领取待确认。"

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert metadata["rules"] == ["remove_unsourced_reward_condition_observation"]
    assert "满足来源中的六项领取条件；具体奖励处理与时机待确认" in enriched
    assert "奖励发放成功" not in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_explicit_new_old_player_example_below_minimum_is_blocked() -> None:
    content = _testcase_artifact(
        [
            "TC-LOW-MIX",
            "正式奖励配置",
            "第1场奖金池计算",
            "功能",
            "P1",
            "第1场有效活动",
            "新玩家2人，老玩家1人",
            "按正式单价计算奖金池",
            "奖金池为40元",
            "保留计算过程",
            "无",
        ]
    )
    source = "\n".join(
        [
            "| 场次 | 新客户奖励 | 老客户奖励 | 预算底标 | 最低核销人数 |",
            "|---:|---:|---:|---:|---:|",
            "| 1 | 20元 | 0元 | 300元 | 10人 |",
        ]
    )

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert "block_low_new_old_player_example" in metadata["rules"]
    assert "明确的新老玩家合计低于最低核销人数" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_missing_reward_condition_does_not_assert_no_payout() -> None:
    content = _testcase_artifact(
        [
            "TC-REWARD-NO-PAYOUT",
            "城市开局计划 H5 规则.md 第318行",
            "未报名不能领取",
            "功能",
            "P1",
            "用户未报名，其他条件满足",
            "用户B",
            "系统检查六条件",
            "不发放奖励",
            "无奖励发放",
            "自动或手动发放待确认",
        ]
    )
    source = "## 领取奖励条件\n318-323 六项条件；奖励自动发放还是手动领取待确认。"

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert "具体产品处理待确认" in enriched
    assert "不发放奖励" not in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_positive_reward_requires_all_six_condition_evidence() -> None:
    content = _testcase_artifact(
        [
            "TC-VS-REWARD",
            "对抗类规则",
            "胜队玩家获得奖励",
            "功能",
            "P1",
            "比赛结束并确认胜队",
            "胜队A",
            "核对比赛结果",
            "胜队玩家获得本场奖励",
            "比赛结果记录",
            "无",
        ]
    )
    content = content.replace(
        "| source rule | TC-VS-REWARD | source mapping |",
        "| 奖励六条件 | TC-VS-REWARD | 报名、核销、获奖名单、趣看发布动态、"
        "#今天一起开局、@交子立方官方号 |",
    )
    source = "\n".join(
        [
            "## 领取奖励条件",
            "用户需同时满足：App报名、到场核销、进入获奖名单、在趣看发布动态、",
            "动态带#今天一起开局、动态@交子立方官方号。",
        ]
    )

    with pytest.raises(ValueError, match="requires evidence for all six"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert metadata["rules"] == ["condition_incomplete_reward_eligibility"]
    assert "最终奖励资格待确认" in enriched
    assert "六项领取条件的完整证据待补齐" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_approximate_reward_scenario_without_numeric_result_stays_conditional() -> None:
    content = _testcase_artifact(
        [
            "TC-RATIO-NONNUMERIC",
            "source",
            "前50%玩家获奖",
            "功能",
            "P1",
            "多人积分排名",
            "排名结果",
            "选取前50%玩家",
            "排名靠前玩家进入获奖名单",
            "名单与排名一致",
            "无",
        ]
    )
    source = "每场获奖人数按约 50% 测算。开发计算建议：人数 × 50%。"

    with pytest.raises(ValueError, match="approximate ratios"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert metadata["rules"] == ["condition_approximate_suggestion"]
    assert "按来源约50%建议核对" in enriched
    assert "若采用来源当前建议" in enriched
    assert "获奖比例及取整规则待确认" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_growth_tier_partial_match_is_not_rewritten_as_no_tier() -> None:
    content = _testcase_artifact(
        [
            "TC-GROWTH-TIER-1",
            "source",
            "满足档位1但不满足档位2和3",
            "功能",
            "P1",
            "3场、30人、15条",
            "档位数据",
            "核对成长金资格",
            "获得成长金500元",
            "成长金记录为500元",
            "成长金发放时机待确认",
        ]
    )
    source = "同一圈子只领取最高档。成长金发放时机仍待确认。"

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert "核对满足条件时选择的最高成长金档位" in enriched
    assert "未满足任何已确认成长金档位" not in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_confirmed_activity_scopes_are_not_reopened_as_merge_question() -> None:
    content = _testcase_artifact(
        [
            "TC-ACTIVITY-SCOPES",
            "source",
            "两种有效活动口径",
            "功能",
            "P1",
            "分别准备四条件和三条件活动",
            "活动数据",
            "分别核对两个统计口径",
            "按各自条件计数",
            "口径核对记录",
            "两套有效活动口径是否统一",
        ]
    )
    source = "\n".join(
        [
            "奖励场次还要求：有到场核销 / 签到 / 平台确认记录。",
            "成长金口径：App内发布｜报名人数大于5人｜活动实际完成。",
        ]
    )

    with pytest.raises(ValueError, match="separately confirmed"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert metadata["rules"] == ["preserve_distinct_activity_scopes"]
    assert "分别按来源执行" in enriched
    assert "是否统一" not in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_incomplete_combat_classification_is_blocked_and_complete_case_is_added() -> None:
    content = _testcase_artifact(
        [
            "TC-COMBAT-PARTIAL",
            "source condition 1",
            "仅有明确对抗关系",
            "功能",
            "P1",
            "活动为队伍对队伍",
            "队伍A与队伍B",
            "系统判断活动类型",
            "归类为对抗类",
            "分类结果",
            "无",
        ]
    )
    source = "\n".join(
        [
            "1. 活动有明确的对抗关系，比如队伍对队伍。",
            "2. 活动有明确胜负或排名规则。",
            "3. 活动结束后，能确认获胜队伍、获胜个人或排名靠前用户。",
        ]
    )

    with pytest.raises(ValueError, match="requires all three sourced conditions"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )

    assert metadata == {
        "artifact": "testcases",
        "rules": [
            "block_incomplete_combat_classification",
            "source_combat_definition",
        ],
        "source_rows": 0,
        "generated_case_id": None,
        "normalized_case_ids": ["TC-COMBAT-PARTIAL"],
    }
    assert "单个条件不足以判定对抗类" in enriched
    assert "| TC-COMBAT-SOURCE |" in enriched
    assert "| 对抗类活动三条件同时成立 | TC-COMBAT-SOURCE |" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_negative_combat_classification_is_not_treated_as_positive_assertion() -> None:
    content = _testcase_artifact(
        [
            "TC-COMBAT-NEGATIVE",
            "source",
            "无对抗关系",
            "功能",
            "P1",
            "活动不具备对抗关系",
            "普通交流活动",
            "核对三项条件",
            "不标记为对抗类",
            "三项条件核对记录",
            "系统分类入口待确认",
        ]
    )
    source = "\n".join(
        [
            "1. 活动有明确的对抗关系，比如队伍对队伍。",
            "2. 活动有明确胜负或排名规则。",
            "3. 活动结束后，能确认获胜队伍、获胜个人或排名靠前用户。",
        ]
    )

    _quality_check("testcases", content, source_corpus=source)


def test_complete_combat_synonyms_are_recognized() -> None:
    content = _testcase_artifact(
        [
            "TC-COMBAT-SYNONYMS",
            "source",
            "队伍对抗赛",
            "功能",
            "P1",
            "明确两队对抗，比分定胜负，结束后可获取比分",
            "比赛结果",
            "核对对抗关系、规则和赛后结果",
            "活动类型标识为对抗类",
            "三类活动证据",
            "分类入口待确认",
        ]
    )
    source = "\n".join(
        [
            "1. 活动有明确的对抗关系，比如队伍对队伍。",
            "2. 活动有明确胜负或排名规则。",
            "3. 活动结束后，能确认获胜队伍、获胜个人或排名靠前用户。",
        ]
    )

    _quality_check("testcases", content, source_corpus=source)
    unchanged, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert unchanged == content
    assert metadata is None


def test_source_config_enrichment_is_recorded_in_run_events(tmp_path: Path) -> None:
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
            summary="candidate",
            artifacts={"testcases": default_recorded_artifact("testcases", "核对配置")},
            evidence=["sources/config.md"],
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    workspace = harness.init_workspace("demo")
    (workspace / "sources/config.md").write_text(
        "\n".join(
            [
                "| 场次 | 新客户奖励 | 老客户奖励 | 预算底标 | 最低核销人数 |",
                "|---:|---:|---:|---:|---:|",
                "| 1 | 20元 | 0元 | 300元 | 10人 |",
            ]
        ),
        encoding="utf-8",
    )

    snapshot = harness.run(TaskRequest(workspace="demo", goal="核对配置"))

    assert snapshot.status == "needs_human_review"
    candidate = tmp_path / snapshot.candidates[0].path
    assert "TC-CONFIG-SOURCE" in candidate.read_text(encoding="utf-8")
    events = [
        json.loads(line)
        for line in (workspace / "runs" / snapshot.run_id / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    enrichment = next(
        event for event in events if event["type"] == "artifact_deterministically_enriched"
    )
    assert enrichment["data"]["source_rows"] == 1


def test_testcase_quality_gate_rejects_incomplete_coverage_placeholders() -> None:
    content = _testcase_artifact(
        [
            "TC-001",
            "source",
            "valid case",
            "功能",
            "P1",
            "ready",
            "data",
            "step",
            "result",
            "evidence",
            "无",
        ]
    ).replace(
        "| source rule | TC-001 | source mapping |",
        "| growth tiers | 暂无 | 未覆盖，需后续设计 |",
    )

    with pytest.raises(ValueError, match="incomplete placeholder mappings"):
        _quality_check("testcases", content)


def test_testcase_quality_gate_rejects_fixed_approximate_suggestion() -> None:
    content = _testcase_artifact(
        [
            "TC-CALC-001",
            "source",
            "10人按50%获奖",
            "功能",
            "P1",
            "核销人数10人",
            "10×50%=5",
            "查看H5",
            "H5固定显示获奖人数5人",
            "显示5人",
            "奖励发放机制",
        ]
    )
    source = "每场获奖人数按约 50% 测算。开发计算建议：人数 × 50%。"

    with pytest.raises(ValueError, match="approximate ratios"):
        _quality_check("testcases", content, source_corpus=source)


def test_testcase_quality_gate_accepts_conditional_suggestion() -> None:
    content = _testcase_artifact(
        [
            "TC-CALC-001",
            "source",
            "10人按50%建议测算",
            "规则确认",
            "P1",
            "核销人数10人",
            "10×50%=5",
            "不执行",
            "若采用当前建议，预计获奖人数为5，最终规则待确认",
            "按建议计算的说明",
            "获奖比例与取整建议待确认",
        ]
    )
    source = "每场获奖人数按约 50% 测算。开发计算建议：人数 × 50%。"

    _quality_check("testcases", content, source_corpus=source)


def test_testcase_quality_gate_rejects_executable_low_count_case() -> None:
    content = _testcase_artifact(
        [
            "TC-MIN-001",
            "source",
            "核销9人低于最低要求",
            "功能",
            "P1",
            "活动已发布",
            "核销人数9人",
            "1. 完成活动<br>2. 查看奖励状态",
            "系统提示人数不足或不发放奖励",
            "观察产品提示",
            "具体产品行为待确认",
        ]
    )
    source = "最低核销人数为10人。"

    with pytest.raises(ValueError, match="non-executable notes"):
        _quality_check("testcases", content, source_corpus=source)


def test_testcase_quality_gate_rejects_non_two_team_combat_misclassification() -> None:
    content = _testcase_artifact(
        [
            "TC-CAT-001",
            "source",
            "非两队的个人赛",
            "功能",
            "P1",
            "个人对个人且有胜负",
            "两名玩家",
            "打开H5",
            "按非对抗活动展示普通文案",
            "不展示胜队文案",
            "无",
        ]
    )
    source = "对抗类包括队伍对队伍、个人对个人和多人积分排名。"

    with pytest.raises(ValueError, match="does not prove"):
        _quality_check("testcases", content, source_corpus=source)


def test_testcase_quality_gate_rejects_unconfirmed_content_judgment() -> None:
    content = _testcase_artifact(
        [
            "TC-CONTENT-001",
            "source",
            "灌水内容无效",
            "功能",
            "P1",
            "用户发布重复内容",
            "重复文本",
            "发布内容后查看统计",
            "系统判定内容无效并不计入",
            "显示内容无效",
            "真实性算法待确认",
        ]
    )
    source = "内容“真实有效”、灌水和刷量的具体判定方式仍待确认。"

    with pytest.raises(ValueError, match="authenticity"):
        _quality_check("testcases", content, source_corpus=source)


def test_all_four_content_conditions_do_not_bypass_authenticity_gate() -> None:
    content = _testcase_artifact(
        [
            "TC-CONTENT-ALL",
            "城市开局计划 H5 规则.md:内容四条件",
            "内容满足全部四条件",
            "功能",
            "P1",
            "动态发布在对应圈子且活动期内",
            "与活动相关的动态",
            "核对四项条件",
            "系统识别动态满足条件，内容计数+1",
            "规则文档6.3，内容统计增加",
            "内容真实有效的判定方式待确认",
        ]
    )
    source = "内容“真实有效”、灌水和刷量的具体判定方式仍待确认。"

    with pytest.raises(ValueError, match="authenticity"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert metadata["rules"] == ["block_unconfirmed_content_judgment"]
    assert "不产生计数或有效性结果断言" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_single_content_condition_does_not_assert_positive_count() -> None:
    content = _testcase_artifact(
        [
            "TC-CONTENT-SINGLE",
            "内容条件：发布在对应圈子内",
            "圈子内动态计入统计",
            "功能",
            "P1",
            "用户在圈子C发布动态",
            "动态一条",
            "发布动态",
            "该动态计入圈子C内容数",
            "圈子C内容数+1",
            "无",
        ]
    )
    source = "内容“真实有效”、灌水和刷量的具体判定方式仍待确认。"

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert metadata["rules"] == ["condition_incomplete_content_eligibility"]
    assert "当前单项条件通过不代表内容可计数" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_coverage_matrix_must_map_each_sourced_reward_and_content_condition() -> None:
    content = _testcase_artifact(
        [
            "TC-GENERIC",
            "source",
            "generic",
            "功能",
            "P1",
            "precondition",
            "data",
            "step",
            "result",
            "evidence",
            "无",
        ]
    )
    source = "\n".join(
        [
            "## 领取奖励条件",
            "在 App 内报名；到场核销；进入获奖名单；在趣看发布动态；",
            "动态带#今天一起开局；动态@交子立方官方号。",
            "内容需发布在对应圈子内、与圈子活动相关、在活动期内发布、真实有效。",
            "内容“真实有效”、灌水和刷量的具体判定方式仍待确认。",
        ]
    )

    with pytest.raises(ValueError) as error:
        _quality_check("testcases", content, source_corpus=source)

    message = str(error.value)
    assert "all six sourced reward conditions" in message
    assert "all four sourced content conditions" in message


def test_testcase_quality_gate_rejects_unconfirmed_growth_payout_evidence() -> None:
    content = _testcase_artifact(
        [
            "TC-GROWTH-001",
            "source",
            "成长金最高档不叠加",
            "功能",
            "P1",
            "满足三档",
            "8场、100人、50条",
            "检查档位选择",
            "选择1500元档位",
            "成长金记录为1500元",
            "成长金发放时机待确认",
        ]
    )
    source = "同一圈子只领取最高档。成长金发放时机仍待确认。"

    with pytest.raises(ValueError, match="payout timing"):
        _quality_check("testcases", content, source_corpus=source)


def test_growth_tier_failure_does_not_invent_display_outcome() -> None:
    content = _testcase_artifact(
        [
            "TC-GROWTH-NOT-MET",
            "成长金档位1",
            "参与玩家不足档位1",
            "功能",
            "P1",
            "有效活动3场，参与玩家29人，内容15条",
            "圈子C",
            "系统计算成长金",
            "不显示档位1成长金或显示未达标",
            "断言无成长金并显示进度",
            "展示方式待确认",
        ]
    ).replace(
        "| source rule | TC-GROWTH-NOT-MET | source mapping |",
        "| 成长金档位1未达标 | TC-GROWTH-NOT-MET | 参与玩家不足时不满足档位1 |",
    )
    source = "成长金档位1要求3场、30人、15条；成长金发放时机待确认。"

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert "remove_unconfirmed_growth_payout" in metadata["rules"]
    assert "仅核对未满足任何已确认成长金档位" in enriched
    assert "核对来源门槛与满足条件时的最高档位选择" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_reward_config_filename_does_not_turn_reward_case_into_growth_case() -> None:
    content = _testcase_artifact(
        [
            "TC-REWARD-CONFIG",
            "奖励与成长金配置.md",
            "第1场奖金池计算",
            "功能",
            "P1",
            "新玩家10人，老玩家0人",
            "正式奖励单价",
            "计算奖金池",
            "奖金池按正式配置计算",
            "保留计算过程",
            "底标展示待确认",
        ]
    )
    source = "成长金发放时机待确认。"

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert enriched == content
    assert metadata is None


def test_coverage_rows_do_not_fix_unconfirmed_reward_growth_or_combat_outcomes() -> None:
    content = _testcase_artifact(
        [
            "TC-GENERIC-COVERAGE",
            "source",
            "generic",
            "功能",
            "P1",
            "precondition",
            "data",
            "step",
            "result",
            "evidence",
            "无",
        ]
    ).replace(
        "| source rule | TC-GENERIC-COVERAGE | source mapping |",
        "\n".join(
            [
                "| 奖励领取-全部满足 | TC-GENERIC-COVERAGE | 验证奖励发放 |",
                "| 成长金档位1 | TC-GENERIC-COVERAGE | 达标后领取500元 |",
                "| 对抗类全部满足 | TC-GENERIC-COVERAGE | 标记并展示胜队文案 |",
            ]
        ),
    )
    source = "\n".join(
        [
            "## 领取奖励条件",
            "成长金发放时机待确认。",
            "前端展示建议：对抗类可以展示为胜队预计人均可领。",
        ]
    )

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert {
        "condition_reward_payout_coverage",
        "condition_growth_payout_coverage",
        "condition_combat_display_coverage",
    }.issubset(metadata["rules"])
    assert "奖励处理与时机待确认" in enriched
    assert "展示与发放待确认" in enriched
    assert "展示建议待确认" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_requirement_quality_gate_rejects_unsourced_delivery_channel() -> None:
    content = "\n".join(
        [
            "# Requirement Analysis",
            "## 来源",
            "- source",
            "## 已确认规则",
            "- 奖励到账。",
            "## 推断",
            "- 可能发放到 App 账户余额。",
            "## 待确认项",
            "- 发放方式待确认。",
        ]
    )

    with pytest.raises(ValueError, match="implementation details"):
        _quality_check("requirement_analysis", content, source_corpus="奖励到账，方式待确认。")


def test_testcase_quality_gate_rejects_unsourced_reward_account() -> None:
    content = _testcase_artifact(
        [
            "TC-REWARD-001",
            "source",
            "奖励资格",
            "功能",
            "P1",
            "满足条件",
            "user",
            "检查资格",
            "符合奖励条件",
            "用户奖励账户显示奖励",
            "发放观察点待确认",
        ]
    )

    with pytest.raises(ValueError, match="implementation observations"):
        _quality_check("testcases", content, source_corpus="满足全部条件可获得奖励。")


def test_testcase_quality_gate_rejects_fixed_combat_display_suggestion() -> None:
    content = _testcase_artifact(
        [
            "TC-VS-001",
            "source",
            "对抗类活动展示",
            "功能",
            "P1",
            "三条件均满足",
            "两队比赛",
            "查看H5",
            "H5展示胜队人均奖励",
            "显示胜队文案",
            "展示规则待确认",
        ]
    )
    source = "前端展示建议：篮球对抗类活动可以展示为胜队预计人均可领。"

    with pytest.raises(ValueError, match="fixed UI assertion"):
        _quality_check("testcases", content, source_corpus=source)


def test_recommended_activity_card_style_stays_conditional() -> None:
    content = _testcase_artifact(
        [
            "TC-UI-CARD",
            "source",
            "H5活动列表卡片",
            "UI",
            "P2",
            "多个活动",
            "活动名称与场次",
            "查看卡片元素",
            "展示活动名称、场次和按钮立即报名，底部小字说明",
            "固定文案和元素检查",
            "无",
        ]
    )
    source = "# 推荐样式文案\n按钮：立即报名\n底部小字：奖励以核销数据为准。"

    with pytest.raises(ValueError, match="recommended activity-card copy"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert metadata["rules"] == ["condition_recommended_card_style"]
    assert "不作为已确认固定界面断言" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_testcase_quality_gate_requires_every_formal_reward_stage() -> None:
    content = _testcase_artifact(
        [
            "TC-CONFIG-001",
            "source",
            "第1场正式配置",
            "配置",
            "P0",
            "正式配置已提供",
            "第1场：新玩家20元、老玩家0元、预算底标300元、最低核销10人",
            "核对配置",
            "四项值一致",
            "配置文本",
            "无",
        ]
    )
    source = "\n".join(
        [
            "| 场次 | 新客户奖励 | 老客户奖励 | 预算底标 | 最低核销人数 |",
            "|---:|---:|---:|---:|---:|",
            "| 1 | 20元 | 0元 | 300元 | 10人 |",
            "| 2 | 25元 | 16元 | 240元 | 10人 |",
        ]
    )

    with pytest.raises(ValueError, match=r"missing stages: \[2\]"):
        _quality_check("testcases", content, source_corpus=source)


def test_testcase_quality_gate_accepts_labeled_reward_config_shorthand() -> None:
    content = _testcase_artifact(
        [
            "TC-CONFIG-001",
            "source",
            "正式配置表驱动核对",
            "配置",
            "P0",
            "正式配置已提供",
            "第1场：新20元/老0元/底标300元/最低核销10人；"
            "第2场：新25元/老16元/底标240元/最低核销10人",
            "核对配置",
            "各标签值与正式配置一致",
            "配置文本",
            "无",
        ]
    )
    source = "\n".join(
        [
            "| 1 | 20元 | 0元 | 300元 | 10人 |",
            "| 2 | 25元 | 16元 | 240元 | 10人 |",
        ]
    )

    _quality_check("testcases", content, source_corpus=source)


def test_testcase_quality_gate_rejects_conflicting_reward_example() -> None:
    content = _testcase_artifact(
        [
            "TC-CONFIG-001",
            "source",
            "第1场正式配置",
            "配置",
            "P0",
            "正式配置已提供",
            "第1场：新玩家20元、老玩家0元、预算底标300元、最低核销10人",
            "核对配置",
            "第1场单价（如新玩家2元，老玩家1元）",
            "配置文本",
            "无",
        ]
    )
    source = "| 1 | 20元 | 0元 | 300元 | 10人 |"

    with pytest.raises(ValueError, match="conflict with the formal"):
        _quality_check("testcases", content, source_corpus=source)


def test_testcase_quality_gate_rejects_unlabeled_conflicting_reward_math() -> None:
    content = _testcase_artifact(
        [
            "TC-CONFIG-MATH",
            "source",
            "第1场奖金池计算",
            "配置",
            "P0",
            "第1场，新老玩家各5人",
            "第1场配置：新100，老80",
            "计算奖金池=5×100+5×80",
            "奖金池为900元",
            "计算过程",
            "无",
        ]
    )
    source = "| 1 | 20元 | 0元 | 300元 | 10人 |"

    with pytest.raises(ValueError, match="conflict with the formal"):
        _quality_check("testcases", content, source_corpus=source)


def test_testcase_quality_gate_rejects_conflicting_price_in_coverage_mapping() -> None:
    content = _testcase_artifact(
        [
            "TC-CONFIG-001",
            "source",
            "第1场正式配置",
            "配置",
            "P0",
            "正式配置已提供",
            "第1场：新玩家20元、老玩家0元、预算底标300元、最低核销10人",
            "核对配置",
            "四项值一致",
            "配置文本",
            "无",
        ]
    ).replace(
        "| source rule | TC-CONFIG-001 | source mapping |",
        "| 第1场全新玩家 | TC-CONFIG-001 | 新玩家单价4元 |",
    )
    source = "| 1 | 20元 | 0元 | 300元 | 10人 |"

    with pytest.raises(ValueError, match="conflict with the formal"):
        _quality_check("testcases", content, source_corpus=source)


def test_testcase_quality_gate_rejects_unknown_budget_floor_comparison() -> None:
    content = _testcase_artifact(
        [
            "TC-CONFIG-001",
            "source",
            "第1场正式配置",
            "配置",
            "P0",
            "正式配置已提供",
            "第1场：新玩家20元、老玩家0元、预算底标300元、最低核销10人",
            "核对配置",
            "四项值一致",
            "配置文本",
            "无",
        ]
    ).replace(
        "| source rule | TC-CONFIG-001 | source mapping |",
        "| 预算底标风险 | TC-CONFIG-001 | 奖金池605<1000，标记未达成 |",
    )
    source = "| 1 | 20元 | 0元 | 300元 | 10人 |"

    with pytest.raises(ValueError, match="conflict with the formal"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert metadata["rules"] == ["remove_conflicting_reward_coverage"]
    assert "605<1000" not in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_unconfirmed_budget_floor_display_is_reduced_to_state_check() -> None:
    content = _testcase_artifact(
        [
            "TC-FLOOR-DISPLAY",
            "source",
            "预算底标未达展示",
            "功能",
            "P1",
            "奖金池低于正式预算底标",
            "正式配置",
            "查看页面",
            "页面显示未达底标提示文案",
            "提示文本可见",
            "展示位置待确认",
        ]
    )
    source = "低于预算底标时标记未达成底标；具体展示位置和文案仍待确认。"

    with pytest.raises(ValueError, match="UI location and copy"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert metadata["rules"] == ["remove_unsourced_budget_floor_display"]
    assert "标记为未达成底标" in enriched
    assert "展示位置和文案待确认" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_formal_unit_prices_are_not_treated_as_confirmed_ui_display() -> None:
    content = _testcase_artifact(
        [
            "TC-PRICE-DISPLAY",
            "source",
            "新老玩家单价展示",
            "功能",
            "P1",
            "正式配置存在",
            "第1场新老玩家",
            "查看页面",
            "页面正确显示新老玩家不同单价",
            "新玩家显示X元，老玩家显示Y元",
            "展示规则待确认",
        ]
    )
    source = "| 1 | 20元 | 0元 | 300元 | 10人 |"

    with pytest.raises(ValueError, match="not a confirmed UI display"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases",
        content,
        source_corpus=source,
    )
    assert metadata is not None
    assert "remove_unsourced_reward_config_display" in metadata["rules"]
    assert "不使用示意金额或展示假设" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


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


def test_reward_stage_after_last_configured_stage_must_reuse_last_prices() -> None:
    content = _testcase_artifact(
        [
            "TC-STAGE-11",
            "source",
            "第11场沿用第10场配置",
            "功能",
            "P0",
            "已完成10场",
            "第11场",
            "核对奖励配置",
            "新玩家500元，老玩家200元，底标2000元",
            "配置快照",
            "无",
        ]
    )
    source = "\n".join(
        [
            "| 10 | 65元 | 56元 | 840元 | 10人 |",
            "第 10 场及以后使用新玩家 65 元、老玩家 56 元。",
        ]
    )

    with pytest.raises(ValueError, match="conflict with the formal"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "remove_conflicting_reward_example" in metadata["rules"]
    assert "500元" not in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_unlimited_growth_ranking_scenario_is_non_executable() -> None:
    content = _testcase_artifact(
        [
            "TC-GROWTH-RANK",
            "成长金同档排序",
            "模拟同档超额排序",
            "功能",
            "P2",
            "修改配置，将名额设为1",
            "两个达标圈子",
            "系统排序发放",
            "参与玩家多的圈子优先获得成长金",
            "发放结果",
            "当前名额不限",
        ]
    )
    source = "三个档位当前均不限名额，因此同档超额排序在当前配置下不会实际触发。"

    with pytest.raises(ValueError, match="unlimited growth-fund configuration"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "block_untriggerable_growth_ranking" in metadata["rules"]
    assert "不执行" in enriched
    assert "修改配置" not in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_rounding_suggestion_with_arrow_example_remains_conditional() -> None:
    content = _testcase_artifact(
        [
            "TC-ROUND",
            "获奖人数取整",
            "验证取整计算",
            "功能",
            "P1",
            "参与人数为5人",
            "2.5→3人",
            "查看预计获奖人数",
            "展示3人，符合≥0.5向上、<0.5向下",
            "显示与计算一致",
            "无",
        ]
    )
    source = "每场活动获奖人数按实际参与人数的约 50%测算。开发计算建议；取整规则建议。"

    with pytest.raises(ValueError, match="calculation/rounding suggestions"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "condition_approximate_suggestion" in metadata["rules"]
    assert "最终比例及取整规则待确认" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_budget_floor_shorthand_does_not_assert_unconfirmed_display() -> None:
    content = _testcase_artifact(
        [
            "TC-FLOOR",
            "奖励底标",
            "验证低于底标",
            "功能",
            "P1",
            "奖金池低于底标",
            "正式配置",
            "查看奖金池",
            "标记并展示底标",
            "展示正确",
            "无",
        ]
    )
    source = "低于预算底标时标记未达成底标；具体展示位置和文案仍待确认。"

    with pytest.raises(ValueError, match="UI location and copy"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "remove_unsourced_budget_floor_display" in metadata["rules"]
    _quality_check("testcases", enriched, source_corpus=source)


def test_effective_activity_definition_does_not_invent_product_observation() -> None:
    content = _testcase_artifact(
        [
            "TC-EFFECTIVE",
            "奖励有效活动定义",
            "核对奖励有效活动四条件",
            "功能",
            "P0",
            "App发布、报名7人、活动完成、有核销记录",
            "活动A",
            "检查奖励模块中的有效性标记",
            "系统标记活动A有效",
            "奖励模块计数增加",
            "无",
        ]
    )
    source = "有到场核销 / 签到 / 平台确认记录；App内发布｜报名人数大于5人｜活动实际完成"

    with pytest.raises(ValueError, match="do not establish a product module"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "condition_effective_activity_observation" in metadata["rules"]
    assert "产品标记、计数入口与观察点待确认" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_partial_combat_condition_cannot_assert_displayed_result() -> None:
    content = _testcase_artifact(
        [
            "TC-COMBAT-PARTIAL",
            "对抗类条件2",
            "核对胜负规则",
            "功能",
            "P1",
            "活动有胜负规则",
            "比分多者胜",
            "结束后查看结果",
            "系统显示胜队",
            "胜队展示正确",
            "无",
        ]
    )
    source = "明确的对抗关系；明确胜负或排名规则；活动结束后能确认获胜结果"

    with pytest.raises(ValueError, match="single combat condition"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "condition_partial_combat_evidence" in metadata["rules"]
    assert "单项输入不能推导最终分类或展示结果" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_reward_rule_numbered_condition_alias_is_source_limited() -> None:
    content = _testcase_artifact(
        [
            "TC-R02",
            "奖励规则.md #01 条件1",
            "缺少报名",
            "功能",
            "P0",
            "用户未报名但满足其他条件",
            "用户A",
            "检查奖励入口",
            "不发放奖励",
            "按钮不可领取",
            "无",
        ]
    )
    source = "领取奖励条件：用户需同时满足六项条件"

    with pytest.raises(ValueError, match="sourced condition failure"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "condition_partial_reward_evidence" in metadata["rules"]
    assert "不满足来源中要求同时成立的全部领取条件" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_growth_amount_shorthand_is_reduced_to_tier_selection() -> None:
    content = _testcase_artifact(
        [
            "TC-G02",
            "成长金档位2",
            "满足档位2",
            "功能",
            "P0",
            "满足5场、60人、30条内容",
            "圈子A",
            "核对结果",
            "触发档位2，得1000元",
            "界面显示档位2",
            "成长金发放时机待确认",
        ]
    )
    source = "同一圈子只领取最高一档成长金，不叠加；成长金发放时机待确认。"

    with pytest.raises(ValueError, match="payout timing is unconfirmed"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "remove_unconfirmed_growth_payout" in metadata["rules"]
    assert "仅核对满足条件时选择的最高成长金档位" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_complete_combat_evidence_cannot_be_rewritten_as_negative() -> None:
    content = _testcase_artifact(
        [
            "TC-COMBAT-COMPLETE",
            "对抗类与奖励",
            "完整对抗条件",
            "功能",
            "P0",
            "同一活动满足三对抗条件",
            "两队对抗，胜负规则明确，结束后结果可确认",
            "核对三条件",
            "缺少任一条件时不按对抗类归类",
            "三类来源证据",
            "无",
        ]
    )
    source = "明确的对抗关系；明确胜负或排名规则；活动结束后能确认获胜结果"

    with pytest.raises(ValueError, match="cannot yield a negative classification"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "correct_complete_combat_classification" in metadata["rules"]
    assert "按来源定义归类为对抗类" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_effective_activity_count_increment_requires_confirmed_observation() -> None:
    content = _testcase_artifact(
        [
            "TC-ACTIVITY",
            "奖励有效活动定义",
            "满足四条件",
            "功能",
            "P0",
            "App发布、报名6人、活动完成、有核销",
            "活动A",
            "完成活动并查看结果",
            "计为主理人有效活动",
            "主理人场次数增加，前端展示为有效活动",
            "无",
        ]
    )
    source = "有到场核销 / 签到 / 平台确认记录；App内发布｜报名人数大于5人｜活动实际完成"

    with pytest.raises(ValueError, match="do not establish a product module"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "condition_effective_activity_observation" in metadata["rules"]
    assert "产品标记、计数入口与观察点待确认" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_negative_combat_case_does_not_invent_frontend_marker() -> None:
    content = _testcase_artifact(
        [
            "TC-COMBAT-NEG-UI",
            "对抗类缺少胜负规则",
            "无规则不属于对抗类",
            "功能",
            "P1",
            "活动有两队对抗但没有胜负规则",
            "活动A",
            "检查是否被标记为对抗类",
            "不被识别为对抗类",
            "前端无对抗类标识",
            "无",
        ]
    )
    source = "明确的对抗关系；明确胜负或排名规则；活动结束后能确认获胜结果"

    with pytest.raises(ValueError, match="cannot invent a frontend marker"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "remove_unsourced_combat_ui" in metadata["rules"]
    assert "不断言未定义的前端标识" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_missing_content_condition_does_not_invent_count_observation() -> None:
    content = _testcase_artifact(
        [
            "TC-CONTENT-MISSING",
            "内容条件D01缺失",
            "发布在其他圈子",
            "功能",
            "P1",
            "动态不在对应圈子",
            "动态A",
            "发布后查看内容数",
            "不计入有效内容数",
            "内容数不变",
            "无",
        ]
    )
    source = "内容条件D01：对应圈子；内容“真实有效”的具体判定方式待确认"

    with pytest.raises(ValueError, match="unconfirmed count UI"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "condition_missing_content_evidence" in metadata["rules"]
    assert "单项条件缺失不足以满足来源中的完整内容定义" in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_growth_copy_does_not_require_prior_payout() -> None:
    content = _testcase_artifact(
        [
            "TC-GROWTH-COPY",
            "成长金说明",
            "成长金为非个人奖励",
            "功能",
            "P1",
            "圈子已获得成长金",
            "已获得500元成长金",
            "查看说明",
            "显示成长金非个人奖励",
            "文案可见",
            "展示位置待确认",
        ]
    )
    source = "成长金非个人奖励，仅用于主理人运营的圈子发展使用"

    with pytest.raises(ValueError, match="must not require an unconfirmed payout"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "remove_growth_copy_payout_precondition" in metadata["rules"]
    assert "可访问来源定义的成长金说明内容" in enriched
    assert "已获得500元" not in enriched
    _quality_check("testcases", enriched, source_corpus=source)


def test_participant_dedup_does_not_assume_query_or_display() -> None:
    content = _testcase_artifact(
        [
            "TC-DEDUP",
            "玩家人数去重",
            "同一用户多场只计1人",
            "功能",
            "P1",
            "用户参加同圈两场活动",
            "用户A、圈子A",
            "查询参与玩家统计",
            "玩家数只增加1",
            "前端展示1人",
            "无",
        ]
    )
    source = "同一用户在同一圈子内参加多场有效活动，只算 1 人"

    with pytest.raises(ValueError, match="observation point is not"):
        _quality_check("testcases", content, source_corpus=source)

    enriched, metadata = _deterministically_enrich_artifact(
        "testcases", content, source_corpus=source
    )
    assert metadata is not None
    assert "condition_participant_dedup_observation" in metadata["rules"]
    assert "参与玩家统计入口与观察点待确认" in enriched
    _quality_check("testcases", enriched, source_corpus=source)
