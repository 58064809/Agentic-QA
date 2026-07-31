from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

import yaml
from langgraph.types import Command, interrupt
from pydantic import BaseModel, ConfigDict, Field

from harness.application.model_port import ModelGateway, ModelPolicy
from harness.application.ports import CheckpointProvider
from harness.application.qa_design import (
    catalog_hash,
    render_requirement_catalog,
    render_testcase_set,
)
from harness.application.quality import (
    CandidateAssessment,
    GenerationModelCall,
    GenerationProvenance,
    QualityContext,
)
from harness.application.review_service import apply_review
from harness.application.source import SourceBundle
from harness.domain.budget import Budget, BudgetExceeded, BudgetLimits
from harness.domain.models import (
    ArtifactCandidate,
    EvidenceRequirement,
    HarnessEvent,
    PlanTask,
    QAPlan,
    ReviewDecision,
    RunSnapshot,
    StartRunCommand,
)
from harness.domain.review import validate_review_decision
from harness.domain.schemas.api_discovery import ApiDiscoveryCatalog, ApiDiscoveryExport
from harness.domain.schemas.api_test_cases import (
    API_CASES_SCHEMA_VERSION,
    ApiTestCasesDraft,
    UnconfirmedApiTestCase,
)
from harness.domain.schemas.api_test_cases import (
    SourceRef as ApiSourceRef,
)
from harness.domain.schemas.qa_design import (
    CoverageMapping,
    EvidenceLevel,
    RequirementCatalog,
    RequirementRule,
    RiskCatalog,
    RiskLevel,
    SourceReference,
    TestCase,
    TestCasePatch,
    TestCaseSet,
    apply_testcase_patch,
    validate_testcase_set,
)
from harness.domain.security import sanitize_untrusted
from harness.infrastructure.manifests.registry import AgentRegistry, SkillRegistry, ToolRegistry
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.prompts import PromptCompiler
from harness.infrastructure.quality import QualityStrategyRegistry
from harness.infrastructure.quality.assessment import CandidateAssessmentService
from harness.infrastructure.tools.runtime import ToolRuntime, resolve_execution_base_url
from harness.infrastructure.workflow.graph import HarnessState, compile_harness_graph

UTC = timezone.utc


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class AgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    artifacts: dict[str, str] = Field(default_factory=dict)
    requirement_catalog: RequirementCatalog | None = None
    risk_catalog: RiskCatalog | None = None
    testcase_set: TestCaseSet | None = None
    testcase_patch: TestCasePatch | None = None
    api_test_cases: ApiTestCasesDraft | None = None
    evidence: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    tool_requests: list[ToolRequest] = Field(default_factory=list)


class _TaskExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output: AgentOutput
    assessments: dict[str, CandidateAssessment] = Field(default_factory=dict)
    quality_exhausted_artifacts: set[str] = Field(default_factory=set)
    api_discovery_export: ApiDiscoveryExport | None = None


ARTIFACT_AGENT = {
    "requirement_analysis": "requirement_analyst",
    "testcases": "test_designer",
    "api_test_draft": "api_test_engineer",
    "ui_test_draft": "ui_test_engineer",
    "api_discovery_report": "api_test_engineer",
    "qa_report": "qa_reporter",
    "execution_report": "test_executor",
    "failure_analysis": "failure_triager",
    "bug_draft": "failure_triager",
}

DESIGN_ARTIFACTS = frozenset({"testcases", "api_test_draft", "ui_test_draft"})

MAX_ARTIFACT_REPAIRS = 5
MAX_TESTCASE_BATCH_ATTEMPTS = 3
MAX_QUALITY_REVISIONS = 5
MAX_PLAN_REPAIRS = 3
SOURCE_PREFETCH_AGENTS: frozenset[str] = frozenset()
TESTCASE_RULE_BATCH_SIZE = 6


class _ModelUsageTracker:
    def __init__(self, initial: dict[str, int]) -> None:
        self._usage = dict(initial)
        self._lock = Lock()

    def add(self, usage: dict[str, int]) -> None:
        with self._lock:
            for key, value in usage.items():
                amount = max(int(value), 0)
                if amount:
                    self._usage[key] = self._usage.get(key, 0) + amount

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._usage)


def _last_call_usage(model: ModelGateway | None) -> dict[str, int]:
    getter = getattr(model, "last_call_usage", None)
    return dict(getter()) if callable(getter) else {}


def _last_call_diagnostics(model: ModelGateway | None) -> dict[str, Any]:
    getter = getattr(model, "last_call_diagnostics", None)
    return dict(getter()) if callable(getter) else {}


def build_default_plan(request: StartRunCommand) -> QAPlan:
    """Deterministic recorded-model fixture; production planning still uses the model."""
    tasks: list[PlanTask] = []
    expected = set(request.expected_artifacts)
    design_artifacts = expected & DESIGN_ARTIFACTS
    needs_catalog = bool(design_artifacts or "requirement_analysis" in expected)
    if needs_catalog:
        analysis_outputs = ["analysis_context"]
        if "requirement_analysis" in expected:
            analysis_outputs.append("requirement_analysis")
        tasks.append(
            PlanTask(
                id="analyze_requirements",
                objective="逐来源提取并合并唯一的强类型 RequirementCatalog",
                agent="requirement_analyst",
                expected_outputs=analysis_outputs,
                evidence_requirements=[
                    EvidenceRequirement(kind="source", description="冻结来源路径和证据引用")
                ],
            )
        )
    if design_artifacts:
        tasks.append(
            PlanTask(
                id="analyze_risks",
                objective="仅基于 RequirementCatalog 生成强类型 RiskCatalog",
                agent="risk_strategist",
                dependencies=["analyze_requirements"],
                inputs=["analyze_requirements"],
                expected_outputs=["risk_context"],
                evidence_requirements=[
                    EvidenceRequirement(kind="trace", description="规则到风险的可追踪映射")
                ],
            )
        )
    for artifact in request.expected_artifacts:
        if artifact == "requirement_analysis":
            continue
        dependencies = (
            ["analyze_requirements", "analyze_risks"] if artifact in design_artifacts else []
        )
        tasks.append(
            PlanTask(
                id=f"produce_{artifact}",
                objective=f"生成可审核候选产物 {artifact}",
                agent=ARTIFACT_AGENT[artifact],
                dependencies=dependencies,
                inputs=["user_goal", *dependencies],
                expected_outputs=[artifact],
                evidence_requirements=[
                    EvidenceRequirement(kind="trace", description="证据或待确认项")
                ],
            )
        )
    return QAPlan(
        tasks=tasks,
        rationale="需求目录只生成一次；风险与测试设计消费同一强类型事实源。",
    )


def _testcase_template(goal: str) -> str:
    return render_testcase_set(default_recorded_testcase_set(goal))


def default_recorded_requirement_catalog(goal: str) -> RequirementCatalog:
    return RequirementCatalog(
        sources=[SourceReference(source="user_goal", section="request.goal")],
        flows=[goal],
        rules=[
            RequirementRule(
                rule_id="GOAL-001",
                title="用户提交的测试目标",
                condition="执行用户明确要求的测试目标",
                outcome=goal,
                evidence_level=EvidenceLevel.CONFIRMED,
                source_refs=[SourceReference(source="user_goal", section="request.goal")],
            )
        ],
        pending_questions=["补充可追踪需求来源、测试环境和验收规则。"],
    )


def default_recorded_testcase_set(goal: str) -> TestCaseSet:
    return TestCaseSet(
        cases=[
            TestCase(
                case_id="TC-001",
                rule_ids=["GOAL-001"],
                title="验证用户目标主流程",
                test_type="功能",
                priority="P1",
                preconditions=["已准备隔离的测试环境"],
                test_data=["使用脱敏且可重复的测试数据"],
                steps=["按用户目标执行主流程", "记录流程产生的可观察结果"],
                expected_results=[f"可观察结果满足用户目标：{goal}"],
                assertions=["保存业务输出或界面状态作为审核证据"],
                pending_items=["具体环境、数据和观察点需人工确认"],
            )
        ],
        coverage=[
            CoverageMapping(
                rule_id="GOAL-001",
                case_ids=["TC-001"],
                rationale="直接覆盖用户提交的测试目标",
            )
        ],
    )


def default_recorded_artifact(artifact: str, goal: str) -> str:
    if artifact == "testcases":
        return _testcase_template(goal)
    if artifact == "requirement_analysis":
        return render_requirement_catalog(default_recorded_requirement_catalog(goal))
    if artifact == "api_test_draft":
        return _render_api_test_cases(default_recorded_api_test_cases(goal))
    title = artifact.replace("_", " ").title()
    return "\n".join(
        [
            "---",
            "schema_version: agentic-qa.harness.artifact.v2",
            f"artifact_type: {artifact}",
            "status: needs_human_review",
            "---",
            "",
            f"# {title} 候选",
            "",
            f"## 测试目标\n\n{goal}",
            "",
            "## 当前结论",
            "",
            "证据不足，当前仅形成可审核框架，不将待确认内容表述为事实。",
            "",
            "## 待确认项",
            "",
            "- 补充可追踪需求来源、测试环境和验收规则。",
        ]
    )


def default_recorded_api_test_cases(goal: str) -> ApiTestCasesDraft:
    source = ApiSourceRef(
        source_type="user_goal",
        source_path="user_goal",
        chunk_id="goal",
        locator="goal",
        summary=goal,
        confidence="low",
    )
    return ApiTestCasesDraft(
        schema_version=API_CASES_SCHEMA_VERSION,
        artifact_type="api_automation_cases",
        status="needs_human_review",
        human_review_required=True,
        base_url_env="AGENTIC_QA_BASE_URL",
        business_rules=[{"id": "GOAL-001", "summary": goal}],
        source_refs=[source],
        cases=[
            UnconfirmedApiTestCase(
                id="API-PENDING-001",
                title="待 OpenAPI 契约确认后补充可执行 API 用例",
                priority="P1",
                contract_status="missing",
                business_rule_refs=["GOAL-001"],
                review_status="needs_human_review",
                review_questions=["请提供完整 OpenAPI 3.x 或 Swagger 2.0 契约。"],
                source_refs=[source],
                pending=["endpoint method、path、参数、响应和安全定义待契约确认"],
                request={"method": None, "path": None},
                assertions=[],
                variables={},
                cleanup=[],
            )
        ],
        review_questions=["请提供完整 OpenAPI 3.x 或 Swagger 2.0 契约。"],
    )


class HarnessEngine:
    def __init__(
        self,
        *,
        store: FilesystemStore,
        agents: AgentRegistry,
        skills: SkillRegistry,
        tools: ToolRegistry,
        quality_policies: QualityStrategyRegistry,
        checkpoint_provider: CheckpointProvider,
        model: ModelGateway | None,
        limits: BudgetLimits | None = None,
        tool_handlers: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.agents = agents
        self.skills = skills
        self.tools = tools
        self.quality_policies = quality_policies
        self.assessment = CandidateAssessmentService(quality_policies)
        self.checkpoint_provider = checkpoint_provider
        self.model = model
        self.model_policy = ModelPolicy()
        self.prompt_compiler = PromptCompiler(agents=agents, skills=skills)
        self.limits = limits or BudgetLimits()
        self.tool_handlers = tool_handlers or {}
        self._event_lock = Lock()

    def execute(
        self,
        request: StartRunCommand,
        emit: Any | None = None,
        *,
        tool_handlers: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> RunSnapshot:
        if self.model is None:
            raise RuntimeError(
                "未配置模型；设置 DEEPSEEK_API_KEY，"
                "或显式配置 AGENTIC_QA_MODEL 和模型密钥环境变量，"
                "或显式注入 ModelGateway"
            )
        run_id = run_id or f"run-{datetime.now(tz=UTC):%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id):
            raise ValueError("run_id 不安全")
        snapshot = RunSnapshot(
            run_id=run_id,
            workspace_id=request.workspace_id,
            status="planning",
            request=request,
        )
        self.store.create_run(snapshot)
        self.store.create_source_bundle(snapshot.workspace_id, snapshot.run_id)
        active_handlers = self.tool_handlers if tool_handlers is None else tool_handlers
        self._freeze_external_tool_snapshots(snapshot, active_handlers)
        initial: HarnessState = {
            "run_id": run_id,
            "request": request.model_dump(mode="json"),
            "task_results": [],
            "processed_results": 0,
            "completed_tasks": [],
            "pending_tasks": [],
            "results_by_task": {},
            "candidates": [],
            "review_status": {},
            "delegations": [],
            "errors": [],
            "status": "planning",
        }
        return self._invoke(snapshot, initial, emit=emit, tool_handlers=active_handlers)

    def _freeze_external_tool_snapshots(
        self,
        snapshot: RunSnapshot,
        tool_handlers: dict[str, Any],
    ) -> None:
        for name, handler in tool_handlers.items():
            owner = getattr(handler, "__self__", None)
            tool_snapshot = getattr(owner, "snapshot", None)
            if tool_snapshot is None:
                continue
            self.store.write_tool_record(
                snapshot.workspace_id,
                snapshot.run_id,
                f"{name.replace('.', '-')}-snapshot.json",
                {
                    "schema_version": "agentic-qa.harness.mcp-tool-snapshot.v2",
                    "tool": name,
                    "snapshot": tool_snapshot.model_dump(mode="json"),
                },
            )

    def resume(
        self,
        snapshot: RunSnapshot,
        decision: ReviewDecision | None = None,
        emit: Any | None = None,
        *,
        tool_handlers: dict[str, Any] | None = None,
    ) -> RunSnapshot:
        if snapshot.status in {"partial", "on_hold"}:
            if decision is None:
                return snapshot
            return apply_review(self.store, snapshot, decision)
        if snapshot.status == "needs_human_review" and decision is None:
            return snapshot
        if snapshot.status not in {
            "planning",
            "recoverable",
            "running",
            "needs_human_review",
        }:
            raise ValueError(f"run 当前状态不可恢复: {snapshot.status}")
        command: Command[Any] | None = None
        if decision is not None:
            validate_review_decision(snapshot, decision)
            command = Command(resume=decision.model_dump(mode="json"))
        active_handlers = self.tool_handlers if tool_handlers is None else tool_handlers
        return self._invoke(
            snapshot,
            command,
            emit=emit,
            tool_handlers=active_handlers,
        )

    def _invoke(
        self,
        snapshot: RunSnapshot,
        graph_input: HarnessState | Command[Any] | None,
        *,
        emit: Any | None,
        tool_handlers: dict[str, Any],
    ) -> RunSnapshot:
        budget = Budget(self.limits, snapshot.budget.model_copy(deep=True))
        model_usage = _ModelUsageTracker(snapshot.model_usage)
        sequence = self.store.next_event_sequence(snapshot.workspace_id, snapshot.run_id)

        def event(event_type: str, **kwargs: Any) -> None:
            nonlocal sequence
            with self._event_lock:
                item = HarnessEvent(
                    sequence=sequence,
                    run_id=snapshot.run_id,
                    type=event_type,
                    task_id=kwargs.pop("task_id", None),
                    agent=kwargs.pop("agent", None),
                    data=sanitize_untrusted(kwargs),
                )
                sequence += 1
                self.store.append_event(snapshot.workspace_id, item)
                if event_type == "model_routed":
                    snapshot.model_routes.append(dict(item.data))
                if emit:
                    emit(item)

        runtime = ToolRuntime(
            store=self.store,
            agents=self.agents,
            tools=self.tools,
            budget=budget,
            handlers=tool_handlers,
            on_call=lambda payload: event(
                "tool_called",
                agent=payload.get("agent"),
                tool=payload.get("tool"),
                status=payload.get("status"),
            ),
        )
        source_bundle = self.store.load_source_bundle(snapshot.workspace_id, snapshot.run_id)
        nodes = self._nodes(snapshot, budget, runtime, model_usage, event, source_bundle)
        config = {
            "configurable": {
                "thread_id": f"{snapshot.workspace_id}:{snapshot.run_id}",
            }
        }
        try:
            with self.checkpoint_provider.open() as checkpointer:
                graph = compile_harness_graph(
                    checkpointer=checkpointer,
                    max_concurrent_agents=self.limits.max_concurrent_agents,
                    **nodes,
                )
                graph.invoke(graph_input, config)
                state_view = graph.get_state(config)
                result = self._project(
                    snapshot,
                    state_view.values,
                    budget,
                    state_view.interrupts,
                    model_usage=model_usage.snapshot(),
                )
        except BudgetExceeded as exc:
            snapshot.errors.append(str(exc))
            snapshot.status = "partial"
            self._ensure_partial_candidates(snapshot)
            snapshot.budget = budget.snapshot()
            snapshot.model_usage = model_usage.snapshot()
            self.store.save_snapshot(snapshot)
            event("budget_exceeded", error=str(exc))
            return snapshot
        except Exception as exc:
            if isinstance(graph_input, Command) and snapshot.status == "needs_human_review":
                event(
                    "review_rejected",
                    error=f"{type(exc).__name__}: {str(exc)[:500]}",
                )
                raise
            snapshot.status = "recoverable"
            message = f"{type(exc).__name__}: {str(exc)[:500]}"
            if message not in snapshot.errors:
                snapshot.errors.append(message)
            snapshot.budget = budget.snapshot()
            snapshot.model_usage = model_usage.snapshot()
            self.store.save_snapshot(snapshot)
            event("run_recoverable", error=message)
            return snapshot
        self.store.save_snapshot(result)
        return result

    def _nodes(
        self,
        snapshot: RunSnapshot,
        budget: Budget,
        runtime: ToolRuntime,
        model_usage: _ModelUsageTracker,
        event: Any,
        source_bundle: SourceBundle,
    ) -> dict[str, Any]:
        request = snapshot.request

        def planner(_state: HarnessState) -> dict[str, Any]:
            if self.model is None:  # guarded by execute, retained for type narrowing
                raise RuntimeError("model is not configured")
            route = self.model_policy.for_planner(request)
            agent_catalog = [
                {
                    "name": item.name,
                    "role": item.role,
                    "skills": item.skills,
                    "tool_allowlist": item.tool_allowlist,
                }
                for item in self.agents.list()
            ]
            validation_feedback: list[dict[str, str]] = []
            compiled_prompt = self.prompt_compiler.compile(
                phase="planner",
                agent="qa_supervisor",
                response_model=QAPlan,
            )
            plan: QAPlan | None = None
            fallback_reason = ""
            for attempt in range(1, MAX_PLAN_REPAIRS + 1):
                budget.consume_model()
                event(
                    "model_routed",
                    agent="qa_supervisor",
                    prompt_template_version=compiled_prompt.template_version,
                    prompt_sha256=compiled_prompt.content_sha256,
                    prompt_reference_versions=compiled_prompt.reference_versions,
                    **self.model.describe_route(route),
                )
                try:
                    try:
                        plan = self.model.structured(
                            system=compiled_prompt.content,
                            prompt=self.prompt_compiler.user_message(
                                compiled_prompt,
                                trusted_context={
                                    "expected_artifacts": request.expected_artifacts,
                                    "available_agents": agent_catalog,
                                    "validation_feedback": validation_feedback,
                                },
                                untrusted_context={"goal": request.goal},
                            ),
                            response_model=QAPlan,
                            route=route,
                        )
                    finally:
                        model_usage.add(_last_call_usage(self.model))
                except RuntimeError as exc:
                    if not _is_invalid_structured_output(exc):
                        raise
                    error = str(exc)[:500]
                    fallback_reason = f"invalid_structured_output: {error}"
                    validation_feedback.append(
                        {"code": "invalid_structured_output", "detail": error}
                    )
                    event(
                        "plan_output_invalid",
                        agent="qa_supervisor",
                        attempt=attempt,
                        error=error,
                    )
                    continue
                try:
                    self._validate_plan(plan, request)
                except ValueError as exc:
                    error = str(exc)[:500]
                    fallback_reason = f"qa_plan_validation: {error}"
                    validation_feedback.append({"code": "qa_plan_validation", "detail": error})
                    event(
                        "plan_validation_failed",
                        agent="qa_supervisor",
                        attempt=attempt,
                        error=error,
                    )
                    continue
                break
            else:
                plan = build_default_plan(request)
                self._validate_plan(plan, request)
                event(
                    "plan_fallback_applied",
                    agent="qa_supervisor",
                    failed_attempts=MAX_PLAN_REPAIRS,
                    reason=fallback_reason,
                    fallback="deterministic_artifact_topology",
                )
            if plan is None:  # defensive guard; every successful loop assigns a validated plan
                raise RuntimeError("planner produced no validated plan")
            pending_task_ids = [task.id for task in plan.tasks]
            ready = _ready_task_ids(
                plan,
                pending_task_ids,
                [],
            )[: self.limits.max_concurrent_agents]
            delegations = [{"task_ids": ready, "revision": plan.revision}]
            event("plan_created", task_count=len(plan.tasks), revision=plan.revision)
            event("tasks_delegated", task_ids=ready)
            return {
                "plan": plan.model_dump(mode="json"),
                "pending_tasks": [task.id for task in plan.tasks],
                "status": "running",
                "delegations": delegations,
            }

        def expert_agent(worker: dict[str, Any]) -> dict[str, Any]:
            task = PlanTask.model_validate(worker["task"])
            event("agent_started", task_id=task.id, agent=task.agent)
            try:
                execution = self._run_task(
                    task=task,
                    request=StartRunCommand.model_validate(worker["request"]),
                    dependencies=worker.get("dependencies", {}),
                    run_id=worker["run_id"],
                    budget=budget,
                    runtime=runtime,
                    model_usage=model_usage,
                    event=event,
                    source_bundle=source_bundle,
                )
                result = {
                    "task_id": task.id,
                    "agent": task.agent,
                    "ok": True,
                    "output": execution.output.model_dump(mode="json"),
                    "assessments": {
                        artifact: assessment.model_dump(mode="json")
                        for artifact, assessment in execution.assessments.items()
                    },
                    "quality_exhausted_artifacts": sorted(execution.quality_exhausted_artifacts),
                    "api_discovery_export": (
                        execution.api_discovery_export.model_dump(mode="json")
                        if execution.api_discovery_export is not None
                        else None
                    ),
                }
                event("agent_completed", task_id=task.id, agent=task.agent)
            except BudgetExceeded:
                raise
            except Exception as exc:
                result = {
                    "task_id": task.id,
                    "agent": task.agent,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                }
                event(
                    "agent_failed",
                    task_id=task.id,
                    agent=task.agent,
                    error=result["error"],
                )
            return {"task_results": [result]}

        def supervisor(state: HarnessState) -> dict[str, Any]:
            results = state.get("task_results", [])
            start = state.get("processed_results", 0)
            new_results = results[start:]
            pending = list(state.get("pending_tasks", []))
            completed = list(state.get("completed_tasks", []))
            outputs = dict(state.get("results_by_task", {}))
            candidates = list(state.get("candidates", []))
            review_status = dict(state.get("review_status", {}))
            plan = QAPlan.model_validate(state["plan"])
            for result in new_results:
                task_id = result["task_id"]
                if result["ok"]:
                    output = AgentOutput.model_validate(result["output"])
                    assessments = {
                        artifact: CandidateAssessment.model_validate(value)
                        for artifact, value in result.get("assessments", {}).items()
                    }
                    quality_exhausted_artifacts = set(result.get("quality_exhausted_artifacts", []))
                    api_discovery_export = (
                        ApiDiscoveryExport.model_validate(result["api_discovery_export"])
                        if result.get("api_discovery_export") is not None
                        else None
                    )
                    outputs[task_id] = output.model_dump(mode="json")
                    if task_id in pending:
                        pending.remove(task_id)
                    if task_id not in completed:
                        completed.append(task_id)
                    for artifact, _content in output.artifacts.items():
                        if artifact not in request.expected_artifacts:
                            event(
                                "task_output_accepted",
                                task_id=task_id,
                                agent=result["agent"],
                                output=artifact,
                            )
                            continue
                        assessment = assessments.get(artifact)
                        if assessment is None:
                            raise RuntimeError(f"任务缺少已执行的质量评估: {artifact}")
                        assessment_key = assessment.report.assessment_key
                        stored = self.store.load_candidate(
                            workspace=request.workspace_id,
                            run_id=snapshot.run_id,
                            artifact=artifact,
                        )
                        if stored is not None and stored.assessment_key == assessment_key:
                            candidate, created = stored, False
                        else:
                            candidate, created = self.store.commit_candidate(
                                workspace=request.workspace_id,
                                run_id=snapshot.run_id,
                                artifact=artifact,
                                assessment=assessment,
                                partial=artifact in quality_exhausted_artifacts,
                                evidence=output.evidence,
                                api_discovery_export=(
                                    api_discovery_export
                                    if artifact == "api_discovery_report"
                                    else None
                                ),
                            )
                        if artifact not in {item["artifact"] for item in candidates}:
                            candidates.append(candidate.model_dump(mode="json"))
                        review_status[artifact] = (
                            "needs_revision"
                            if artifact in quality_exhausted_artifacts
                            else "needs_human_review"
                        )
                        needs_quality_event = created or not self.store.has_assessment_event(
                            request.workspace_id,
                            snapshot.run_id,
                            candidate.assessment_key or "",
                        )
                        if needs_quality_event:
                            report = self.store.load_quality_report(candidate)
                            event(
                                "artifact_quality_evaluated",
                                task_id=task_id,
                                agent=result["agent"],
                                artifact=artifact,
                                assessment_key=candidate.assessment_key,
                                source_bundle_hash=candidate.source_bundle_hash,
                                policy_versions=candidate.policy_versions,
                                reviewer_roles=sorted(
                                    {
                                        strategy.reviewer_role
                                        for variant in report.variants
                                        for strategy in variant.strategies
                                    }
                                ),
                                publishable_variants=[
                                    item.variant.value for item in report.variants if item.passed
                                ],
                            )
                        if created:
                            event(
                                "candidate_written",
                                task_id=task_id,
                                agent=result["agent"],
                                artifact=artifact,
                                path=candidate.path,
                            )
                else:
                    budget.consume_replan()
                    plan = plan.model_copy(
                        update={
                            "revision": plan.revision + 1,
                            "rationale": f"主管重试 {task_id}: {result['error']}",
                        }
                    )
                    event(
                        "plan_revised",
                        task_id=task_id,
                        agent="qa_supervisor",
                        revision=plan.revision,
                        reason=result["error"],
                    )
            ready = _ready_task_ids(plan, pending, completed)[: self.limits.max_concurrent_agents]
            delegations = list(state.get("delegations", []))
            if ready:
                delegations.append({"task_ids": ready, "revision": plan.revision})
                event("tasks_delegated", task_ids=ready)
            return {
                "plan": plan.model_dump(mode="json"),
                "pending_tasks": pending,
                "completed_tasks": completed,
                "results_by_task": outputs,
                "processed_results": len(results),
                "candidates": candidates,
                "review_status": review_status,
                "delegations": delegations,
            }

        def prepare_review(state: HarnessState) -> dict[str, Any]:
            if state.get("pending_tasks"):
                raise RuntimeError("计划无法继续：依赖未满足")
            artifacts = {item["artifact"] for item in state.get("candidates", [])}
            missing = set(request.expected_artifacts) - artifacts
            if missing:
                raise ValueError(f"任务未生成委派产物: {sorted(missing)}")
            candidates = [
                ArtifactCandidate.model_validate(item) for item in state.get("candidates", [])
            ]
            if any(item.partial for item in candidates):
                event(
                    "generation_quality_exhausted",
                    artifacts=sorted(item.artifact for item in candidates if item.partial),
                )
                return {"status": "partial"}
            event("review_required", artifacts=sorted(artifacts))
            return {"status": "needs_human_review"}

        def review_gate(state: HarnessState) -> dict[str, Any]:
            decision = interrupt(
                {
                    "schema_version": "agentic-qa.harness.review-gate.v2",
                    "run_id": snapshot.run_id,
                    "artifacts": [
                        {
                            "artifact": item["artifact"],
                            "path": item["path"],
                            "publishable_variants": [
                                version.variant.value
                                for version in ArtifactCandidate.model_validate(item).versions
                                if self.store.load_quality_report(
                                    ArtifactCandidate.model_validate(item)
                                ).verdict_for(version.variant)
                            ],
                        }
                        for item in state.get("candidates", [])
                    ],
                    "message": "候选已停止在 Review Gate，等待人工 ReviewDecision。",
                }
            )
            return {"review_decision": decision}

        def review_node(state: HarnessState) -> dict[str, Any]:
            current = self._snapshot_from_state(snapshot, state, budget, interrupt_value=None)
            decision = ReviewDecision.model_validate(state["review_decision"])
            reviewed = apply_review(self.store, current, decision)
            return {
                "status": reviewed.status,
                "review_status": reviewed.review_status,
                "review_decision": {},
            }

        return {
            "planner": planner,
            "expert_agent": expert_agent,
            "supervisor": supervisor,
            "prepare_review": prepare_review,
            "review_gate": review_gate,
            "apply_review": review_node,
        }

    def _validate_plan(self, plan: QAPlan, request: StartRunCommand) -> None:
        produced: set[str] = set()
        for task in plan.tasks:
            self.agents.get(task.agent)
            if not task.evidence_requirements:
                raise ValueError(f"QAPlan task 必须声明证据要求: {task.id}")
            produced.update(task.expected_outputs)
        missing = set(request.expected_artifacts) - produced
        if missing:
            raise ValueError(f"QAPlan 未覆盖期望产物: {sorted(missing)}")
        for artifact in request.expected_artifacts:
            producers = [task for task in plan.tasks if artifact in task.expected_outputs]
            if len(producers) != 1:
                raise ValueError(f"QAPlan 中期望产物必须且只能由一个任务生成: {artifact}")
            expected_agent = ARTIFACT_AGENT.get(artifact)
            if expected_agent and producers[0].agent != expected_agent:
                raise ValueError(
                    f"{artifact} 必须由 {expected_agent} 生成，不能委派给 {producers[0].agent}"
                )
            if artifact == "api_discovery_report" and producers[0].dependencies:
                raise ValueError(
                    "api_discovery_report producer must not depend on requirement or risk tasks"
                )
            if artifact in DESIGN_ARTIFACTS:
                requirement_tasks = [
                    task
                    for task in plan.tasks
                    if task.agent == "requirement_analyst"
                    and not task.dependencies
                    and "analysis_context" in task.expected_outputs
                ]
                if len(requirement_tasks) != 1:
                    raise ValueError(
                        f"{artifact} requires exactly one root RequirementCatalog task"
                    )
                risk_tasks = [
                    task
                    for task in plan.tasks
                    if task.agent == "risk_strategist"
                    and "risk_context" in task.expected_outputs
                    and requirement_tasks[0].id in task.dependencies
                ]
                if len(risk_tasks) != 1:
                    raise ValueError(
                        f"{artifact} requires exactly one RiskCatalog task depending on "
                        "the RequirementCatalog"
                    )
                dependencies = set(producers[0].dependencies)
                required_dependencies = {requirement_tasks[0].id, risk_tasks[0].id}
                if not required_dependencies.issubset(dependencies):
                    raise ValueError(
                        f"{artifact} must directly depend on RequirementCatalog and RiskCatalog"
                    )
        requirement_tasks = [task for task in plan.tasks if task.agent == "requirement_analyst"]
        if len(requirement_tasks) > 1:
            raise ValueError("QAPlan cannot split requirement facts across multiple model tasks")
        if request.expected_artifacts == ["api_discovery_report"] and len(plan.tasks) != 1:
            raise ValueError("standalone api_discovery_report requires exactly one task")

    def _run_task(
        self,
        *,
        task: PlanTask,
        request: StartRunCommand,
        dependencies: dict[str, dict[str, Any]],
        run_id: str,
        budget: Budget,
        runtime: ToolRuntime,
        model_usage: _ModelUsageTracker,
        event: Any,
        source_bundle: SourceBundle,
    ) -> _TaskExecution:
        if self.model is None:
            raise RuntimeError("model is not configured")
        manifest = self.agents.get(task.agent)
        model_tool_allowlist = list(manifest.tool_allowlist)
        live_test_base_url: str | None = None
        if task.expected_outputs == ["api_discovery_report"]:
            if _expected_network_capture_sources(source_bundle):
                # Raw captures can contain credentials and personal data. The model only
                # receives the deterministic inspector's sanitized result for this task.
                model_tool_allowlist = ["network.capture.inspect"]
            else:
                if (
                    request.execution_profile.environment == "analysis-only"
                    or not request.execution_profile.allow_ui_mutations
                ):
                    raise PermissionError(
                        "live api_discovery_report requires an explicit UI-enabled "
                        "test environment when no frozen capture exists"
                    )
                live_test_base_url = resolve_execution_base_url(request.execution_profile)
                model_tool_allowlist = ["mcp.playwright", "network.capture.live"]
        elif manifest.name == "api_test_engineer":
            model_tool_allowlist = [
                tool
                for tool in model_tool_allowlist
                if tool not in {"mcp.playwright", "network.capture.live"}
            ]
        model_tools = runtime.model_tools(model_tool_allowlist)
        if (
            task.expected_outputs == ["api_discovery_report"]
            and live_test_base_url is not None
            and (
                "network.capture.live" not in {tool["name"] for tool in model_tools}
                or "mcp.playwright.browser_navigate" not in {tool["name"] for tool in model_tools}
            )
        ):
            raise RuntimeError(
                "live api_discovery_report requires configured Playwright MCP and "
                "network.capture.live"
            )
        available_tool_names = {item["name"] for item in model_tools}
        tool_results: list[dict[str, Any]] = []
        validation_feedback: list[dict[str, str]] = []
        artifact_repair_attempts = 0
        structured_output_attempts = 0
        quality_revisions = 0
        generation_usage = _ModelUsageTracker({})
        generation_calls: list[dict[str, Any]] = []
        current_testcase_set: TestCaseSet | None = None
        requirement_catalog = _requirement_catalog_from_dependencies(dependencies)
        risk_catalog = _risk_catalog_from_dependencies(dependencies)
        source_files = [document.path for document in source_bundle.readable_documents]
        source_fragments: list[RequirementCatalog] = []
        batched_seed: AgentOutput | None = None
        api_discovery_export: ApiDiscoveryExport | None = None
        expert_prompt = self.prompt_compiler.compile(
            phase="expert",
            agent=manifest.name,
            response_model=AgentOutput,
            tools=model_tools,
        )
        if (
            source_files
            and manifest.name in SOURCE_PREFETCH_AGENTS
            and "workspace.read" in manifest.tool_allowlist
        ):
            for source_path in source_files:
                arguments = {"path": source_path}
                value = runtime.call(
                    workspace=request.workspace_id,
                    run_id=run_id,
                    agent=manifest.name,
                    tool="workspace.read",
                    arguments=arguments,
                    profile=request.execution_profile,
                    idempotency_key=_tool_key(
                        run_id,
                        task.id,
                        -1,
                        "workspace.read",
                        arguments,
                    ),
                )
                tool_results.append({"tool": "workspace.read", "result": value})
        if manifest.name == "requirement_analyst":
            fragment_prompt = self.prompt_compiler.compile(
                phase="requirement-fragment",
                agent=manifest.name,
                response_model=AgentOutput,
                tools=model_tools,
            )
            for document in source_bundle.readable_documents:
                route = self.model_policy.for_task(task)
                route_record = self.model.describe_route(route)
                fragment_result: AgentOutput | None = None
                fragment_feedback: list[dict[str, str]] = []
                for fragment_attempt in range(1, MAX_ARTIFACT_REPAIRS + 1):
                    budget.consume_model()
                    event(
                        "model_routed",
                        task_id=task.id,
                        agent=manifest.name,
                        phase=(
                            "source_fragment" if fragment_attempt == 1 else "source_fragment_repair"
                        ),
                        source=document.path,
                        repair_attempt=fragment_attempt,
                        **route_record,
                    )
                    fragment_usage: dict[str, int] = {}
                    fragment_diagnostics: dict[str, Any] = {}
                    try:
                        try:
                            fragment_result = self.model.structured(
                                system=fragment_prompt.content,
                                prompt=self.prompt_compiler.user_message(
                                    fragment_prompt,
                                    trusted_context={
                                        "task": task.model_dump(mode="json"),
                                        "source_identity": {
                                            "path": document.path,
                                            "raw_sha256": document.raw_sha256,
                                            "parsed_sha256": document.parsed_sha256,
                                        },
                                        "allowed_artifacts": [],
                                        "validation_feedback": fragment_feedback,
                                    },
                                    untrusted_context={
                                        "goal": request.goal,
                                        "source_content": document.text,
                                    },
                                ),
                                response_model=AgentOutput,
                                route=route,
                            )
                        finally:
                            fragment_usage = _last_call_usage(self.model)
                            fragment_diagnostics = _last_call_diagnostics(self.model)
                            model_usage.add(fragment_usage)
                            generation_usage.add(fragment_usage)
                    except RuntimeError as exc:
                        generation_calls.append(
                            {
                                "call_index": len(generation_calls) + 1,
                                **route_record,
                                **fragment_usage,
                                **fragment_diagnostics,
                                "source_selection": [
                                    {
                                        "source": document.path,
                                        "raw_sha256": document.raw_sha256,
                                        "selection_reason": "per_file_structured_extraction",
                                    }
                                ],
                                "prompt_template_version": fragment_prompt.template_version,
                                "prompt_sha256": fragment_prompt.content_sha256,
                                "prompt_reference_versions": fragment_prompt.reference_versions,
                                "outcome": "invalid_structured_output",
                                "artifact_validation_retries": fragment_attempt,
                                "failure_stage": "source_fragment_extraction",
                            }
                        )
                        if (
                            not _is_invalid_structured_output(exc)
                            or fragment_attempt == MAX_ARTIFACT_REPAIRS
                        ):
                            raise
                        fragment_feedback = [
                            {
                                "kind": "structured_output",
                                "error": str(exc)[:500],
                            }
                        ]
                        event(
                            "model_output_invalid",
                            task_id=task.id,
                            agent=manifest.name,
                            phase="source_fragment",
                            source=document.path,
                            attempt=fragment_attempt,
                            error=str(exc)[:500],
                        )
                        continue
                    break
                if fragment_result is None:  # pragma: no cover - loop invariant
                    raise RuntimeError(f"source fragment extraction failed: {document.path}")
                if fragment_result.requirement_catalog is None:
                    raise ValueError(f"source fragment {document.path} omitted requirement_catalog")
                _validate_catalog_sources(fragment_result.requirement_catalog, source_bundle)
                missing_document_refs = [
                    rule.rule_id
                    for rule in fragment_result.requirement_catalog.rules
                    if rule.evidence_level == EvidenceLevel.CONFIRMED
                    and document.path not in {reference.source for reference in rule.source_refs}
                ]
                if missing_document_refs:
                    raise ValueError(
                        f"source fragment {document.path} has confirmed rules without a "
                        f"reference to that document: {missing_document_refs}"
                    )
                source_fragments.append(fragment_result.requirement_catalog)
                generation_calls.append(
                    {
                        "call_index": len(generation_calls) + 1,
                        **route_record,
                        **fragment_usage,
                        **fragment_diagnostics,
                        "source_selection": [
                            {
                                "source": document.path,
                                "raw_sha256": document.raw_sha256,
                                "selection_reason": "per_file_structured_extraction",
                            }
                        ],
                        "prompt_template_version": fragment_prompt.template_version,
                        "prompt_sha256": fragment_prompt.content_sha256,
                        "prompt_reference_versions": fragment_prompt.reference_versions,
                        "outcome": "completed",
                    }
                )
            if len(source_fragments) == 1:
                fragment = source_fragments[0]
                batched_seed = AgentOutput(
                    summary="Use the validated single-source requirement catalog directly",
                    requirement_catalog=fragment,
                    evidence=[
                        f"source_fragment:{reference.source}" for reference in fragment.sources
                    ],
                )
        if manifest.name == "test_designer":
            if requirement_catalog is None:
                raise ValueError("test_designer has no RequirementCatalog dependency")
            if risk_catalog is None:
                raise ValueError("test_designer has no RiskCatalog dependency")
            batch_prompt = self.prompt_compiler.compile(
                phase="testcase-rule-batch",
                agent=manifest.name,
                response_model=AgentOutput,
                tools=model_tools,
            )
            testcase_fragments: list[TestCaseSet] = []
            for batch in _testcase_rule_batches(
                requirement_catalog,
                risk_catalog,
                batch_size=TESTCASE_RULE_BATCH_SIZE,
            ):
                batch_catalog = _catalog_for_rule_ids(requirement_catalog, set(batch["rule_ids"]))
                batch_risks = RiskCatalog(
                    risks=[
                        risk
                        for risk in risk_catalog.risks
                        if set(risk.rule_ids) & set(batch["rule_ids"])
                    ]
                )
                budget.consume_model()
                route = self.model_policy.for_task(task)
                route_record = self.model.describe_route(route)
                event(
                    "model_routed",
                    task_id=task.id,
                    agent=manifest.name,
                    phase="rule_batch",
                    batch_id=batch["batch_id"],
                    rule_ids=batch["rule_ids"],
                    **route_record,
                )
                batch_usage: dict[str, int] = {}
                batch_diagnostics: dict[str, Any] = {}
                try:
                    try:
                        batch_result = self.model.structured(
                            system=batch_prompt.content,
                            prompt=self.prompt_compiler.user_message(
                                batch_prompt,
                                trusted_context={
                                    "task": task.model_dump(mode="json"),
                                    "rule_batch": batch,
                                    "requirement_catalog": batch_catalog.model_dump(mode="json"),
                                    "risk_catalog": batch_risks.model_dump(mode="json"),
                                    "allowed_artifacts": [],
                                },
                                untrusted_context={
                                    "goal": request.goal,
                                    "tool_results": [],
                                },
                            ),
                            response_model=AgentOutput,
                            tools=model_tools,
                            route=route,
                        )
                    finally:
                        batch_usage = _last_call_usage(self.model)
                        batch_diagnostics = _last_call_diagnostics(self.model)
                        model_usage.add(batch_usage)
                        generation_usage.add(batch_usage)
                except RuntimeError as exc:
                    generation_calls.append(
                        {
                            "call_index": len(generation_calls) + 1,
                            **route_record,
                            **batch_usage,
                            **batch_diagnostics,
                            "source_selection": _catalog_source_selection(
                                batch_catalog, source_bundle
                            ),
                            "prompt_template_version": batch_prompt.template_version,
                            "prompt_sha256": batch_prompt.content_sha256,
                            "prompt_reference_versions": batch_prompt.reference_versions,
                            "outcome": "invalid_structured_output",
                            "failure_stage": "testcase_rule_batch",
                        }
                    )
                    if not _is_invalid_structured_output(exc):
                        raise
                    repaired, retry_calls = self._repair_testcase_batch(
                        task=task,
                        goal=request.goal,
                        manifest=manifest,
                        model_tools=model_tools,
                        batch=batch,
                        catalog=batch_catalog,
                        risks=batch_risks,
                        source_bundle=source_bundle,
                        budget=budget,
                        model_usage=model_usage,
                        generation_usage=generation_usage,
                        first_call_index=len(generation_calls) + 1,
                        initial_error=(
                            f"{batch['batch_id']}:invalid_structured_output:{str(exc)[:1000]}"
                        ),
                        runtime=runtime,
                        request=request,
                        run_id=run_id,
                        available_tool_names=available_tool_names,
                        event=event,
                    )
                    testcase_fragments.append(repaired)
                    generation_calls.extend(retry_calls)
                    continue
                if batch_result.tool_requests:
                    batch_tool_results: list[dict[str, Any]] = []
                    for call in batch_result.tool_requests:
                        if call.tool not in available_tool_names:
                            raise PermissionError(
                                f"{manifest.name} requested unavailable tool: {call.tool}"
                            )
                        value = runtime.call(
                            workspace=request.workspace_id,
                            run_id=run_id,
                            agent=manifest.name,
                            tool=call.tool,
                            arguments=call.arguments,
                            profile=request.execution_profile,
                            idempotency_key=call.idempotency_key
                            or _tool_key(
                                run_id,
                                task.id,
                                0,
                                call.tool,
                                call.arguments,
                            ),
                        )
                        batch_tool_results.append({"tool": call.tool, "result": value})
                    generation_calls.append(
                        {
                            "call_index": len(generation_calls) + 1,
                            **route_record,
                            **batch_usage,
                            **batch_diagnostics,
                            "source_selection": _generation_source_selection(
                                batch_tool_results, source_bundle
                            ),
                            "prompt_template_version": batch_prompt.template_version,
                            "prompt_sha256": batch_prompt.content_sha256,
                            "prompt_reference_versions": batch_prompt.reference_versions,
                            "outcome": "completed",
                        }
                    )
                    repaired, retry_calls = self._repair_testcase_batch(
                        task=task,
                        goal=request.goal,
                        manifest=manifest,
                        model_tools=model_tools,
                        batch=batch,
                        catalog=batch_catalog,
                        risks=batch_risks,
                        source_bundle=source_bundle,
                        budget=budget,
                        model_usage=model_usage,
                        generation_usage=generation_usage,
                        first_call_index=len(generation_calls) + 1,
                        initial_error="retrieved_source_evidence_available",
                        runtime=runtime,
                        request=request,
                        run_id=run_id,
                        available_tool_names=available_tool_names,
                        event=event,
                        initial_tool_results=batch_tool_results,
                    )
                    testcase_fragments.append(repaired)
                    generation_calls.extend(retry_calls)
                    continue
                if (
                    batch_result.artifacts
                    or batch_result.testcase_set is None
                    or batch_result.testcase_patch is not None
                ):
                    generation_calls.append(
                        {
                            "call_index": len(generation_calls) + 1,
                            **route_record,
                            **batch_usage,
                            **batch_diagnostics,
                            "source_selection": _catalog_source_selection(
                                batch_catalog, source_bundle
                            ),
                            "prompt_template_version": batch_prompt.template_version,
                            "prompt_sha256": batch_prompt.content_sha256,
                            "prompt_reference_versions": batch_prompt.reference_versions,
                            "outcome": "artifact_validation_rejected",
                            "artifact_validation_retries": 1,
                            "failure_stage": "testcase_rule_batch_contract",
                        }
                    )
                    repaired, retry_calls = self._repair_testcase_batch(
                        task=task,
                        goal=request.goal,
                        manifest=manifest,
                        model_tools=model_tools,
                        batch=batch,
                        catalog=batch_catalog,
                        risks=batch_risks,
                        source_bundle=source_bundle,
                        budget=budget,
                        model_usage=model_usage,
                        generation_usage=generation_usage,
                        first_call_index=len(generation_calls) + 1,
                        initial_error=f"{batch['batch_id']}:invalid_batch_output_contract",
                        runtime=runtime,
                        request=request,
                        run_id=run_id,
                        available_tool_names=available_tool_names,
                        event=event,
                    )
                    testcase_fragments.append(repaired)
                    generation_calls.extend(retry_calls)
                    continue
                batch_set = batch_result.testcase_set.model_copy(
                    update={"requirement_catalog_hash": catalog_hash(batch_catalog)}
                )
                batch_issues = validate_testcase_set(batch_catalog, batch_set)
                if batch_issues:
                    error = (
                        f"{batch['batch_id']} failed validation: "
                        + json.dumps(
                            [item.model_dump(mode="json") for item in batch_issues],
                            ensure_ascii=False,
                        )[:8000]
                    )
                    generation_calls.append(
                        {
                            "call_index": len(generation_calls) + 1,
                            **route_record,
                            **batch_usage,
                            **batch_diagnostics,
                            "source_selection": _catalog_source_selection(
                                batch_catalog, source_bundle
                            ),
                            "prompt_template_version": batch_prompt.template_version,
                            "prompt_sha256": batch_prompt.content_sha256,
                            "prompt_reference_versions": batch_prompt.reference_versions,
                            "outcome": "artifact_validation_rejected",
                            "artifact_validation_retries": 1,
                            "failure_stage": "testcase_rule_batch_validation",
                        }
                    )
                    repaired, retry_calls = self._repair_testcase_batch(
                        task=task,
                        goal=request.goal,
                        manifest=manifest,
                        model_tools=model_tools,
                        batch=batch,
                        catalog=batch_catalog,
                        risks=batch_risks,
                        source_bundle=source_bundle,
                        budget=budget,
                        model_usage=model_usage,
                        generation_usage=generation_usage,
                        first_call_index=len(generation_calls) + 1,
                        initial_error=error,
                        runtime=runtime,
                        request=request,
                        run_id=run_id,
                        available_tool_names=available_tool_names,
                        event=event,
                    )
                    testcase_fragments.append(repaired)
                    generation_calls.extend(retry_calls)
                    continue
                testcase_fragments.append(batch_set)
                generation_calls.append(
                    {
                        "call_index": len(generation_calls) + 1,
                        **route_record,
                        **batch_usage,
                        **batch_diagnostics,
                        "source_selection": _catalog_source_selection(batch_catalog, source_bundle),
                        "prompt_template_version": batch_prompt.template_version,
                        "prompt_sha256": batch_prompt.content_sha256,
                        "prompt_reference_versions": batch_prompt.reference_versions,
                        "outcome": "completed",
                    }
                )
            current_testcase_set = _merge_testcase_batches(requirement_catalog, testcase_fragments)
            batched_seed = AgentOutput(
                summary="Merged independently generated testcase rule batches",
                testcase_set=current_testcase_set,
                evidence=[
                    f"rule_batch:{batch['batch_id']}"
                    for batch in _testcase_rule_batches(
                        requirement_catalog,
                        risk_catalog,
                        batch_size=TESTCASE_RULE_BATCH_SIZE,
                    )
                ],
            )
        for step in range(manifest.max_steps):
            using_batched_seed = batched_seed is not None
            if not using_batched_seed:
                budget.consume_model()
            route = self.model_policy.for_task(task)
            route_record = self.model.describe_route(route)
            prompt_requirement_catalog = requirement_catalog
            prompt_risk_catalog = risk_catalog
            prompt_testcase_set = current_testcase_set
            if (
                manifest.name == "test_designer"
                and current_testcase_set is not None
                and requirement_catalog is not None
            ):
                targeted = _targeted_testcase_patch_context(
                    current_testcase_set,
                    validation_feedback,
                )
                if targeted is not None:
                    prompt_testcase_set, targeted_rule_ids = targeted
                    prompt_requirement_catalog = _catalog_for_rule_ids(
                        requirement_catalog,
                        targeted_rule_ids,
                    )
                    if risk_catalog is not None:
                        prompt_risk_catalog = RiskCatalog(
                            risks=[
                                risk
                                for risk in risk_catalog.risks
                                if set(risk.rule_ids) & targeted_rule_ids
                            ]
                        )
            if not using_batched_seed:
                event(
                    "model_routed",
                    task_id=task.id,
                    agent=manifest.name,
                    **route_record,
                )
            call_usage: dict[str, int] = {}
            call_diagnostics: dict[str, Any] = {}
            try:
                try:
                    result = batched_seed or self.model.structured(
                        system=expert_prompt.content,
                        prompt=self.prompt_compiler.user_message(
                            expert_prompt,
                            trusted_context={
                                "task": task.model_dump(mode="json"),
                                "dependencies": _prompt_dependencies(dependencies, manifest.name),
                                "source_files": source_files,
                                "source_prefetched": bool(tool_results),
                                "requirement_catalog": (
                                    prompt_requirement_catalog.model_dump(mode="json")
                                    if prompt_requirement_catalog is not None
                                    else None
                                ),
                                "risk_catalog": (
                                    prompt_risk_catalog.model_dump(mode="json")
                                    if prompt_risk_catalog is not None
                                    else None
                                ),
                                "rule_batches": (
                                    _testcase_rule_batches(
                                        requirement_catalog,
                                        risk_catalog,
                                        batch_size=TESTCASE_RULE_BATCH_SIZE,
                                    )
                                    if manifest.name == "test_designer"
                                    and requirement_catalog is not None
                                    else []
                                ),
                                "current_testcase_set": (
                                    prompt_testcase_set.model_dump(mode="json")
                                    if prompt_testcase_set is not None
                                    else None
                                ),
                                "source_fragments": [
                                    fragment.model_dump(mode="json")
                                    for fragment in source_fragments
                                ],
                                "allowed_artifacts": task.expected_outputs,
                                "validation_feedback": validation_feedback,
                                "execution_profile": request.execution_profile.model_dump(
                                    mode="json"
                                ),
                                "test_base_url": live_test_base_url,
                            },
                            untrusted_context={
                                "goal": request.goal,
                                "tool_results": sanitize_untrusted(tool_results),
                            },
                        ),
                        response_model=AgentOutput,
                        tools=model_tools,
                        route=route,
                    )
                finally:
                    if not using_batched_seed:
                        call_usage = _last_call_usage(self.model)
                        call_diagnostics = _last_call_diagnostics(self.model)
                        model_usage.add(call_usage)
                        generation_usage.add(call_usage)
                    batched_seed = None
            except RuntimeError as exc:
                if not _is_invalid_structured_output(exc) or step + 1 >= manifest.max_steps:
                    raise
                generation_calls.append(
                    {
                        "call_index": len(generation_calls) + 1,
                        **route_record,
                        **call_usage,
                        **call_diagnostics,
                        "source_selection": _generation_source_selection(
                            tool_results, source_bundle
                        ),
                        "prompt_template_version": expert_prompt.template_version,
                        "prompt_sha256": expert_prompt.content_sha256,
                        "prompt_reference_versions": expert_prompt.reference_versions,
                        "outcome": "invalid_structured_output",
                    }
                )
                error = str(exc)[:500]
                structured_output_attempts += 1
                validation_feedback.append(
                    {
                        "kind": "structured_output",
                        "error": error,
                    }
                )
                event(
                    "model_output_invalid",
                    task_id=task.id,
                    agent=manifest.name,
                    attempt=structured_output_attempts,
                    error=error,
                )
                continue
            if not using_batched_seed:
                generation_calls.append(
                    {
                        "call_index": len(generation_calls) + 1,
                        **route_record,
                        **call_usage,
                        **call_diagnostics,
                        "source_selection": _generation_source_selection(
                            tool_results, source_bundle
                        ),
                        "prompt_template_version": expert_prompt.template_version,
                        "prompt_sha256": expert_prompt.content_sha256,
                        "prompt_reference_versions": expert_prompt.reference_versions,
                        "outcome": "completed",
                    }
                )
            if result.tool_requests:
                for call in result.tool_requests:
                    if call.tool not in available_tool_names:
                        raise PermissionError(
                            f"{manifest.name} requested unavailable tool: {call.tool}"
                        )
                    runtime_tool = call.tool
                    runtime_arguments = call.arguments
                    if call.tool.startswith("mcp.playwright."):
                        runtime_tool = "mcp.playwright"
                        runtime_arguments = {
                            "tool": call.tool.removeprefix("mcp.playwright."),
                            "arguments": call.arguments,
                        }
                    key = call.idempotency_key or _tool_key(
                        run_id, task.id, step, runtime_tool, runtime_arguments
                    )
                    value = runtime.call(
                        workspace=request.workspace_id,
                        run_id=run_id,
                        agent=manifest.name,
                        tool=runtime_tool,
                        arguments=runtime_arguments,
                        profile=request.execution_profile,
                        idempotency_key=key,
                    )
                    tool_results.append(
                        {
                            "tool": runtime_tool,
                            "requested_tool": call.tool,
                            "result": value,
                        }
                    )
                continue
            try:
                if manifest.name == "requirement_analyst":
                    if result.requirement_catalog is None:
                        raise ValueError("requirement_analyst omitted requirement_catalog")
                    if result.artifacts:
                        event(
                            "redundant_model_artifacts_ignored",
                            task_id=task.id,
                            agent=manifest.name,
                            artifacts=sorted(result.artifacts),
                        )
                    _validate_catalog_sources(result.requirement_catalog, source_bundle)
                    _validate_catalog_merge(source_fragments, result.requirement_catalog)
                    requirement_catalog = result.requirement_catalog
                    rendered = {}
                    if "requirement_analysis" in task.expected_outputs:
                        rendered["requirement_analysis"] = render_requirement_catalog(
                            requirement_catalog
                        )
                    result = result.model_copy(update={"artifacts": rendered})
                elif manifest.name == "risk_strategist":
                    if requirement_catalog is None:
                        raise ValueError("risk_strategist has no RequirementCatalog dependency")
                    if result.risk_catalog is None:
                        raise ValueError("risk_strategist omitted risk_catalog")
                    if result.artifacts:
                        event(
                            "redundant_model_artifacts_ignored",
                            task_id=task.id,
                            agent=manifest.name,
                            artifacts=sorted(result.artifacts),
                        )
                    risk_catalog = result.risk_catalog
                    known_rules = {rule.rule_id for rule in requirement_catalog.rules}
                    unknown_rules = {
                        rule_id
                        for risk in result.risk_catalog.risks
                        for rule_id in risk.rule_ids
                        if rule_id not in known_rules
                    }
                    if unknown_rules:
                        raise ValueError(
                            f"RiskCatalog references unknown rules: {sorted(unknown_rules)}"
                        )
                    result = result.model_copy(update={"artifacts": {}})
                elif manifest.name == "test_designer":
                    if requirement_catalog is None:
                        raise ValueError("test_designer has no RequirementCatalog dependency")
                    if risk_catalog is None:
                        raise ValueError("test_designer has no RiskCatalog dependency")
                    if result.artifacts:
                        event(
                            "redundant_model_artifacts_ignored",
                            task_id=task.id,
                            agent=manifest.name,
                            artifacts=sorted(result.artifacts),
                        )
                    if result.testcase_patch is not None:
                        if current_testcase_set is None:
                            raise ValueError("testcase_patch cannot precede an initial set")
                        _validate_targeted_testcase_patch(
                            result.testcase_patch,
                            current_testcase_set,
                            validation_feedback,
                        )
                        current_testcase_set = apply_testcase_patch(
                            current_testcase_set, result.testcase_patch
                        )
                    elif result.testcase_set is not None:
                        if current_testcase_set is not None and not using_batched_seed:
                            raise ValueError(
                                "test_designer must return TestCasePatch after the initial "
                                "batched TestCaseSet"
                            )
                        current_testcase_set = result.testcase_set
                    else:
                        raise ValueError("test_designer omitted testcase_set/testcase_patch")
                    current_testcase_set = current_testcase_set.model_copy(
                        update={"requirement_catalog_hash": catalog_hash(requirement_catalog)}
                    )
                    design_issues = validate_testcase_set(requirement_catalog, current_testcase_set)
                    if design_issues:
                        raise ValueError(
                            json.dumps(
                                [issue.model_dump(mode="json") for issue in design_issues],
                                ensure_ascii=False,
                            )[:8000]
                        )
                    result = result.model_copy(
                        update={
                            "testcase_set": current_testcase_set,
                            "testcase_patch": None,
                            "artifacts": {"testcases": render_testcase_set(current_testcase_set)},
                        }
                    )
                elif (
                    manifest.name == "api_test_engineer"
                    and "api_test_draft" in task.expected_outputs
                ):
                    if result.api_test_cases is None:
                        raise ValueError("api_test_engineer omitted api_test_cases")
                    _validate_api_test_cases(
                        result.api_test_cases,
                        tool_results=tool_results,
                        requirement_catalog=requirement_catalog,
                        source_bundle=source_bundle,
                    )
                    rendered = dict(result.artifacts)
                    if "api_test_draft" in rendered:
                        rendered.pop("api_test_draft")
                        event(
                            "redundant_model_artifacts_ignored",
                            task_id=task.id,
                            agent=manifest.name,
                            artifacts=["api_test_draft"],
                        )
                    rendered["api_test_draft"] = _render_api_test_cases(result.api_test_cases)
                    result = result.model_copy(update={"artifacts": rendered})
                elif (
                    manifest.name == "api_test_engineer"
                    and "api_discovery_report" in task.expected_outputs
                ):
                    discovery_catalogs = _api_discovery_catalogs(
                        tool_results,
                        source_bundle=source_bundle,
                    )
                    if not discovery_catalogs:
                        raise ValueError(
                            "api_discovery_report requires network.capture.inspect on a "
                            "frozen HAR/JSON capture or network.capture.live"
                        )
                    expected_capture_sources = _expected_network_capture_sources(source_bundle)
                    inspected_sources = {catalog.source_path for catalog in discovery_catalogs}
                    missing_capture_sources = expected_capture_sources - inspected_sources
                    if missing_capture_sources:
                        raise ValueError(
                            "api_discovery_report omitted frozen capture sources: "
                            f"{sorted(missing_capture_sources)}"
                        )
                    rendered = dict(result.artifacts)
                    if "api_discovery_report" in rendered:
                        rendered.pop("api_discovery_report")
                        event(
                            "redundant_model_artifacts_ignored",
                            task_id=task.id,
                            agent=manifest.name,
                            artifacts=["api_discovery_report"],
                        )
                    rendered["api_discovery_report"] = _render_api_discovery_report(
                        discovery_catalogs,
                        run_id=run_id,
                    )
                    api_discovery_export = ApiDiscoveryExport(
                        run_id=run_id,
                        catalogs=discovery_catalogs,
                    )
                    result = result.model_copy(update={"artifacts": rendered})
                unexpected = set(result.artifacts) - set(task.expected_outputs)
                if unexpected:
                    raise ValueError(
                        f"agent returned undelegated artifacts: {sorted(unexpected)}; "
                        "structured design outputs must use their typed fields"
                    )
                required = set(task.expected_outputs) & set(ARTIFACT_AGENT)
                missing = required - set(result.artifacts)
                if missing:
                    raise ValueError(f"agent omitted delegated artifacts: {sorted(missing)}")
                if manifest.name == "requirement_analyst" and source_files and not source_fragments:
                    raise ValueError(
                        "requirement_analyst must extract every frozen source before output"
                    )
            except ValueError as exc:
                error = str(exc)[:500]
                artifact_repair_attempts += 1
                generation_calls[-1]["outcome"] = "artifact_validation_rejected"
                generation_calls[-1]["artifact_validation_retries"] = artifact_repair_attempts
                generation_calls[-1]["failure_stage"] = "artifact_validation"
                validation_feedback.append(
                    {
                        "kind": "artifact_validation",
                        "error": error,
                    }
                )
                event(
                    "artifact_validation_failed",
                    task_id=task.id,
                    agent=manifest.name,
                    attempt=artifact_repair_attempts,
                    error=error,
                )
                if artifact_repair_attempts >= MAX_ARTIFACT_REPAIRS:
                    raise ValueError(
                        f"artifact validation failed after {MAX_ARTIFACT_REPAIRS} attempts: {error}"
                    ) from exc
                continue
            configured = (
                self.store.workspace_config(request.workspace_id).get("quality_policies") or []
            )
            strategy_names = ["generic-artifact-contracts", *configured]
            assessments: dict[str, CandidateAssessment] = {}
            blockers: list[dict[str, str]] = []
            remediation_guidance: dict[str, str] = {}
            for artifact, content in result.artifacts.items():
                if artifact not in request.expected_artifacts:
                    continue
                context = QualityContext(
                    workspace_id=request.workspace_id,
                    run_id=run_id,
                    artifact=artifact,
                    source_bundle=source_bundle,
                )
                assessment = self.assessment.assess(
                    context=context,
                    content=content,
                    media_type=_artifact_media_type(artifact),
                    strategy_names=strategy_names,
                )
                assessments[artifact] = assessment
                if assessment.remediation_patch:
                    remediation_guidance[artifact] = assessment.remediation_patch
                if any(variant.passed for variant in assessment.report.variants):
                    continue
                for issue in assessment.report.variants[0].issues:
                    if issue.severity.value == "blocker":
                        blockers.append(
                            {
                                "artifact": artifact,
                                "policy": issue.policy,
                                "code": issue.code,
                                "message": issue.message[:4000],
                                **{
                                    key: str(value)[:500]
                                    for key, value in issue.details.items()
                                    if key in {"rule_id", "case_id", "term"}
                                },
                            }
                        )
            if blockers:
                generation_calls[-1]["outcome"] = "quality_rejected"
                current_case_ids = (
                    {case.case_id for case in current_testcase_set.cases}
                    if current_testcase_set is not None
                    else set()
                )
                current_rule_ids = (
                    {rule_id for case in current_testcase_set.cases for rule_id in case.rule_ids}
                    if current_testcase_set is not None
                    else set()
                )
                repairable = any(
                    item["policy"] != "source-ingestion"
                    and (
                        not item.get("rule_id")
                        and not item.get("case_id")
                        or item.get("rule_id") in current_rule_ids
                        or item.get("case_id") in current_case_ids
                    )
                    for item in blockers
                )
                can_retry = (
                    repairable
                    and quality_revisions < MAX_QUALITY_REVISIONS
                    and step + 1 < manifest.max_steps
                )
                if can_retry:
                    quality_revisions += 1
                    feedback = {
                        "kind": "quality_gate",
                        "error": json.dumps(
                            {
                                "blockers": blockers,
                                "advisory_remediation_patches": remediation_guidance,
                            },
                            ensure_ascii=False,
                        )[:30000],
                        "previous_artifacts": json.dumps(
                            {
                                "affected_artifacts": sorted(
                                    {item["artifact"] for item in blockers}
                                ),
                                "affected_case_ids": sorted(
                                    {
                                        str(item.get("case_id"))
                                        for item in blockers
                                        if item.get("case_id")
                                    }
                                ),
                            },
                            ensure_ascii=False,
                        )[:10000],
                    }
                    validation_feedback.append(feedback)
                    event(
                        "artifact_quality_revision_requested",
                        task_id=task.id,
                        agent=manifest.name,
                        attempt=quality_revisions,
                        blockers=blockers,
                    )
                    continue
            else:
                generation_calls[-1]["outcome"] = "quality_accepted"
            provenance = GenerationProvenance(
                llm_used=True,
                task_id=task.id,
                agent=manifest.name,
                model_calls=tuple(
                    GenerationModelCall.model_validate(item) for item in generation_calls
                ),
                usage=generation_usage.snapshot(),
                structured_output_retries=structured_output_attempts,
                quality_revisions=quality_revisions,
            )
            assessments = {
                artifact: assessment.model_copy(update={"generation": provenance})
                for artifact, assessment in assessments.items()
            }
            return _TaskExecution(
                output=result,
                assessments=assessments,
                quality_exhausted_artifacts={item["artifact"] for item in blockers},
                api_discovery_export=api_discovery_export,
            )
        raise RuntimeError(f"agent step limit exceeded: {manifest.name}")

    def _repair_testcase_batch(
        self,
        *,
        task: PlanTask,
        goal: str,
        manifest: Any,
        model_tools: list[dict[str, Any]],
        batch: dict[str, Any],
        catalog: RequirementCatalog,
        risks: RiskCatalog,
        source_bundle: SourceBundle,
        budget: Budget,
        model_usage: _ModelUsageTracker,
        generation_usage: _ModelUsageTracker,
        first_call_index: int,
        initial_error: str,
        runtime: ToolRuntime,
        request: StartRunCommand,
        run_id: str,
        available_tool_names: set[str],
        event: Any,
        initial_tool_results: list[dict[str, Any]] | None = None,
    ) -> tuple[TestCaseSet, list[dict[str, Any]]]:
        if self.model is None:
            raise RuntimeError("model is not configured")
        repair_prompt = self.prompt_compiler.compile(
            phase="testcase-rule-batch-repair",
            agent=manifest.name,
            response_model=AgentOutput,
            tools=model_tools,
        )
        calls: list[dict[str, Any]] = []
        feedback = initial_error
        batch_tool_results = list(initial_tool_results or [])
        for repair_attempt in range(2, MAX_TESTCASE_BATCH_ATTEMPTS + 1):
            budget.consume_model()
            route = self.model_policy.for_task(task)
            route_record = self.model.describe_route(route)
            event(
                "model_routed",
                task_id=task.id,
                agent=manifest.name,
                phase="rule_batch_repair",
                batch_id=batch["batch_id"],
                rule_ids=batch["rule_ids"],
                repair_attempt=repair_attempt,
                **route_record,
            )
            usage: dict[str, int] = {}
            diagnostics: dict[str, Any] = {}
            try:
                try:
                    result = self.model.structured(
                        system=repair_prompt.content,
                        prompt=self.prompt_compiler.user_message(
                            repair_prompt,
                            trusted_context={
                                "task": task.model_dump(mode="json"),
                                "rule_batch": batch,
                                "requirement_catalog": catalog.model_dump(mode="json"),
                                "risk_catalog": risks.model_dump(mode="json"),
                                "allowed_artifacts": [],
                                "validation_feedback": [
                                    {
                                        "kind": "testcase_rule_batch",
                                        "error": feedback,
                                    }
                                ],
                            },
                            untrusted_context={
                                "goal": goal,
                                "tool_results": sanitize_untrusted(batch_tool_results),
                            },
                        ),
                        response_model=AgentOutput,
                        tools=model_tools,
                        route=route,
                    )
                finally:
                    usage = _last_call_usage(self.model)
                    diagnostics = _last_call_diagnostics(self.model)
                    model_usage.add(usage)
                    generation_usage.add(usage)
            except RuntimeError:
                calls.append(
                    {
                        "call_index": first_call_index + len(calls),
                        **route_record,
                        **usage,
                        **diagnostics,
                        "source_selection": _catalog_source_selection(catalog, source_bundle),
                        "prompt_template_version": repair_prompt.template_version,
                        "prompt_sha256": repair_prompt.content_sha256,
                        "prompt_reference_versions": repair_prompt.reference_versions,
                        "outcome": "invalid_structured_output",
                        "artifact_validation_retries": repair_attempt - 1,
                        "failure_stage": "testcase_rule_batch_repair",
                    }
                )
                if repair_attempt == MAX_TESTCASE_BATCH_ATTEMPTS:
                    fallback = _deterministic_testcase_batch_fallback(catalog, risks)
                    event(
                        "testcase_batch_fallback_applied",
                        task_id=task.id,
                        agent=manifest.name,
                        batch_id=batch["batch_id"],
                        rule_ids=batch["rule_ids"],
                        reason="structured_output_repair_exhausted",
                    )
                    return fallback, calls
                feedback = "response does not satisfy AgentOutput schema"
                continue
            if result.tool_requests:
                for call in result.tool_requests:
                    if call.tool not in available_tool_names:
                        raise PermissionError(
                            f"{manifest.name} requested unavailable tool: {call.tool}"
                        )
                    arguments = call.arguments
                    value = runtime.call(
                        workspace=request.workspace_id,
                        run_id=run_id,
                        agent=manifest.name,
                        tool=call.tool,
                        arguments=arguments,
                        profile=request.execution_profile,
                        idempotency_key=call.idempotency_key
                        or _tool_key(
                            run_id,
                            task.id,
                            repair_attempt,
                            call.tool,
                            arguments,
                        ),
                    )
                    batch_tool_results.append({"tool": call.tool, "result": value})
                calls.append(
                    {
                        "call_index": first_call_index + len(calls),
                        **route_record,
                        **usage,
                        **diagnostics,
                        "source_selection": _generation_source_selection(
                            batch_tool_results, source_bundle
                        ),
                        "prompt_template_version": repair_prompt.template_version,
                        "prompt_sha256": repair_prompt.content_sha256,
                        "prompt_reference_versions": repair_prompt.reference_versions,
                        "outcome": "completed",
                        "artifact_validation_retries": repair_attempt - 1,
                    }
                )
                feedback = "retrieved_source_evidence_available"
                continue
            error: str | None = None
            if result.artifacts or result.testcase_set is None or result.testcase_patch is not None:
                error = f"{batch['batch_id']} must return only testcase_set"
            else:
                candidate = result.testcase_set.model_copy(
                    update={"requirement_catalog_hash": catalog_hash(catalog)}
                )
                issues = validate_testcase_set(catalog, candidate)
                if issues:
                    error = json.dumps(
                        [item.model_dump(mode="json") for item in issues],
                        ensure_ascii=False,
                    )[:8000]
            calls.append(
                {
                    "call_index": first_call_index + len(calls),
                    **route_record,
                    **usage,
                    **diagnostics,
                    "source_selection": _catalog_source_selection(catalog, source_bundle),
                    "prompt_template_version": repair_prompt.template_version,
                    "prompt_sha256": repair_prompt.content_sha256,
                    "prompt_reference_versions": repair_prompt.reference_versions,
                    "outcome": ("completed" if error is None else "artifact_validation_rejected"),
                    "artifact_validation_retries": repair_attempt - 1,
                    "failure_stage": (None if error is None else "testcase_rule_batch_repair"),
                }
            )
            if error is None:
                return candidate, calls
            feedback = error
        fallback = _deterministic_testcase_batch_fallback(catalog, risks)
        event(
            "testcase_batch_fallback_applied",
            task_id=task.id,
            agent=manifest.name,
            batch_id=batch["batch_id"],
            rule_ids=batch["rule_ids"],
            reason=f"artifact_validation_repair_exhausted:{feedback[:500]}",
        )
        return fallback, calls

    def _project(
        self,
        snapshot: RunSnapshot,
        state: HarnessState,
        budget: Budget,
        interrupts: tuple[Any, ...],
        *,
        model_usage: dict[str, int],
    ) -> RunSnapshot:
        interrupt_value = interrupts[0].value if interrupts else None
        return self._snapshot_from_state(
            snapshot,
            state,
            budget,
            interrupt_value=interrupt_value,
            model_usage=model_usage,
        )

    def _snapshot_from_state(
        self,
        snapshot: RunSnapshot,
        state: HarnessState,
        budget: Budget,
        *,
        interrupt_value: dict[str, Any] | None,
        model_usage: dict[str, int] | None = None,
    ) -> RunSnapshot:
        plan = QAPlan.model_validate(state["plan"]) if state.get("plan") else snapshot.plan
        projected_model_usage = snapshot.model_usage if model_usage is None else model_usage
        return snapshot.model_copy(
            deep=True,
            update={
                "status": state.get("status", snapshot.status),
                "plan": plan,
                "completed_tasks": state.get("completed_tasks", []),
                "pending_tasks": state.get("pending_tasks", []),
                "candidates": [
                    ArtifactCandidate.model_validate(item) for item in state.get("candidates", [])
                ],
                "review_status": state.get("review_status", {}),
                "delegations": state.get("delegations", []),
                "tool_calls": self.store.tool_records(snapshot.workspace_id, snapshot.run_id),
                "model_usage": projected_model_usage,
                "model_routes": snapshot.model_routes,
                "interrupt": interrupt_value,
                "errors": list(dict.fromkeys([*snapshot.errors, *state.get("errors", [])])),
                "budget": budget.snapshot(),
            },
        )

    def _ensure_partial_candidates(self, snapshot: RunSnapshot) -> None:
        existing = {candidate.artifact for candidate in snapshot.candidates}
        source_bundle = self.store.load_source_bundle(snapshot.workspace_id, snapshot.run_id)
        configured = (
            self.store.workspace_config(snapshot.workspace_id).get("quality_policies") or []
        )
        strategy_names = ["generic-artifact-contracts", *configured]
        for artifact in snapshot.request.expected_artifacts:
            if artifact in existing:
                continue
            stored = self.store.load_candidate(
                workspace=snapshot.workspace_id,
                run_id=snapshot.run_id,
                artifact=artifact,
            )
            if stored is not None:
                snapshot.candidates.append(stored)
                snapshot.review_status[artifact] = "needs_human_review"
                existing.add(artifact)
                continue
            content = default_recorded_artifact(artifact, snapshot.request.goal)
            context = QualityContext(
                workspace_id=snapshot.workspace_id,
                run_id=snapshot.run_id,
                artifact=artifact,
                source_bundle=source_bundle,
            )
            assessment = self.assessment.assess(
                context=context,
                content=content,
                media_type=_artifact_media_type(artifact),
                strategy_names=strategy_names,
            )
            candidate, _created = self.store.commit_candidate(
                workspace=snapshot.workspace_id,
                run_id=snapshot.run_id,
                artifact=artifact,
                assessment=assessment,
                partial=True,
                evidence=[],
            )
            snapshot.candidates.append(candidate)
            snapshot.review_status[artifact] = "needs_human_review"


def _is_invalid_structured_output(exc: RuntimeError) -> bool:
    message = str(exc)
    return "model_gateway_error" in message and (
        "ValidationError" in message or "json_invalid" in message or "JSONDecodeError" in message
    )


def _artifact_media_type(artifact: str) -> str:
    return "application/yaml" if artifact == "api_test_draft" else "text/markdown"


def _render_api_test_cases(cases: ApiTestCasesDraft) -> str:
    return yaml.safe_dump(
        cases.model_dump(mode="json"),
        allow_unicode=True,
        sort_keys=False,
    )


def _api_discovery_catalogs(
    tool_results: list[dict[str, Any]],
    *,
    source_bundle: SourceBundle,
) -> list[ApiDiscoveryCatalog]:
    frozen_sources = {document.path for document in source_bundle.documents}
    catalogs: dict[str, ApiDiscoveryCatalog] = {}
    for item in tool_results:
        tool = item.get("tool")
        if tool not in {"network.capture.inspect", "network.capture.live"}:
            continue
        raw = item.get("result")
        if not isinstance(raw, dict):
            continue
        catalog = ApiDiscoveryCatalog.model_validate(raw)
        if tool == "network.capture.inspect":
            if catalog.source_path not in frozen_sources:
                raise ValueError(
                    f"API discovery source is not part of the frozen SourceBundle: "
                    f"{catalog.source_path}"
                )
            if catalog.capture_format == "playwright_mcp":
                raise ValueError("offline API discovery cannot claim a live Playwright source")
        elif catalog.capture_format != "playwright_mcp" or not catalog.source_path.startswith(
            "runtime/playwright-network-capture/"
        ):
            raise ValueError("live API discovery has invalid runtime provenance")
        if any(candidate.source_path != catalog.source_path for candidate in catalog.candidates):
            raise ValueError("API discovery candidate source does not match its catalog")
        catalogs[catalog.source_path] = catalog
    return [catalogs[source] for source in sorted(catalogs)]


def _expected_network_capture_sources(source_bundle: SourceBundle) -> set[str]:
    expected: set[str] = set()
    for document in source_bundle.documents:
        path = document.path.casefold()
        if path.endswith(".har") or (
            path.endswith(".json") and ("capture" in path or "network" in path)
        ):
            expected.add(document.path)
    return expected


def _render_api_discovery_report(
    catalogs: list[ApiDiscoveryCatalog],
    *,
    run_id: str,
) -> str:
    lines = [
        "# 接口发现报告",
        "",
        "## 采集来源",
        "",
        "| Run | 来源文件 | 格式 | 非静态调用 | 业务候选 |",
        "|---|---|---|---:|---:|",
    ]
    for catalog in catalogs:
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_cell(run_id),
                    _markdown_cell(catalog.source_path),
                    _markdown_cell(catalog.capture_format),
                    str(catalog.observed_call_count),
                    str(catalog.business_candidate_count),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 接口调用链",
            "",
            "| 顺序 | 来源 | Method | Origin | Path | Status | Resource Type | 页面路径 | "
            "耗时(ms) | 业务候选 |",
            "|---:|---|---|---|---|---:|---|---|---:|---|",
        ]
    )
    call_number = 0
    for catalog in catalogs:
        for call in catalog.calls:
            call_number += 1
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(call_number),
                        _markdown_cell(catalog.source_path),
                        call.method,
                        _markdown_cell(call.origin or "-"),
                        _markdown_cell(call.path),
                        str(call.status or ""),
                        _markdown_cell(call.resource_type or "-"),
                        _markdown_cell(call.page_path or "-"),
                        str(call.duration_ms if call.duration_ms is not None else ""),
                        "是" if call.business_candidate else "否",
                    ]
                )
                + " |"
            )
    if call_number == 0:
        lines.append("| - | - | - | - | 未发现非静态网络调用 | - | - | - | - | 否 |")

    lines.extend(
        [
            "",
            "## 业务接口候选清单",
            "",
            "| 候选 | 来源 | Method | Origin | Path | 调用次数 | 状态码 | Query 字段 | "
            "平均耗时(ms) | 证据级别 |",
            "|---|---|---|---|---|---:|---|---|---:|---|",
        ]
    )
    candidates = [(catalog, candidate) for catalog in catalogs for candidate in catalog.candidates]
    for catalog, candidate in candidates:
        lines.append(
            "| "
            + " | ".join(
                [
                    candidate.candidate_id,
                    _markdown_cell(catalog.source_path),
                    candidate.method,
                    _markdown_cell(candidate.origin or "-"),
                    _markdown_cell(candidate.path),
                    str(candidate.call_count),
                    _markdown_cell(", ".join(map(str, candidate.status_codes)) or "-"),
                    _markdown_cell(", ".join(candidate.query_parameters) or "-"),
                    str(
                        candidate.average_duration_ms
                        if candidate.average_duration_ms is not None
                        else ""
                    ),
                    "observed / playwright-network-capture",
                ]
            )
            + " |"
        )
    if not candidates:
        lines.append("| - | - | - | - | 未发现业务接口候选 | 0 | - | - | - | observed |")

    lines.extend(["", "## 请求与响应结构摘要", ""])
    if not candidates:
        lines.append("未发现可生成结构摘要的业务接口候选。")
    for catalog, candidate in candidates:
        lines.extend(
            [
                f"### {candidate.candidate_id} {candidate.method} "
                f"`{_markdown_code(candidate.path)}`",
                "",
                f"- 来源：`{_markdown_code(catalog.source_path)}`；定位："
                + ", ".join(f"`{_markdown_code(locator)}`" for locator in candidate.locators),
                "- Request Schema 摘要：",
                "",
                *[
                    f"    {line}"
                    for line in json.dumps(
                        candidate.request_schema,
                        ensure_ascii=False,
                        indent=2,
                    ).splitlines()
                ],
                "- Response Schema 摘要：",
                "",
                *[
                    f"    {line}"
                    for line in json.dumps(
                        candidate.response_schema,
                        ensure_ascii=False,
                        indent=2,
                    ).splitlines()
                ],
                "",
            ]
        )

    lines.extend(
        [
            "## 与 OpenAPI 契约的关系",
            "",
            "本报告只记录浏览器网络抓包中的运行时观察，不代表完整 API 契约，也不能替代 "
            "OpenAPI、Swagger 或其他正式协议来源。候选接口的必填字段、枚举、错误码全集、"
            "权限、风控与副作用仍需通过完整契约确认。",
            "",
            "## 可转入 API 测试草稿的建议",
            "",
            "- observed 候选可用于提出主流程、异常响应、鉴权、幂等和重复提交等测试意图。",
            "- 在完整 OpenAPI 确认前，API 测试草稿中的 contract_status 保持未确认，"
            "request.method/path 保持 null。",
            "",
            "## 脱敏说明",
            "",
            "系统未保存原始 header 值、query value、request body value 或完整 response body；"
            "报告仅保留路径归一化结果、字段名和 JSON 类型摘要。",
            "",
        ]
    )
    redactions = sorted({item for catalog in catalogs for item in catalog.redactions})
    if redactions:
        lines.extend(f"- 已脱敏：`{_markdown_code(item)}`" for item in redactions)
    else:
        lines.append("- 本次结构中未识别到需要按字段名标记的敏感项；原始值仍未进入报告。")
    lines.extend(["", "## 待确认问题", ""])
    limitations = list(
        dict.fromkeys(
            [
                *(pending for _catalog, candidate in candidates for pending in candidate.pending),
                *(limitation for catalog in catalogs for limitation in catalog.limitations),
            ]
        )
    )
    lines.extend(f"- {_markdown_text(item)}" for item in limitations)
    return "\n".join(lines).rstrip() + "\n"


def _markdown_cell(value: str) -> str:
    return html.escape(value, quote=True).replace("|", r"\|").replace("\r", " ").replace("\n", " ")


def _markdown_code(value: str) -> str:
    return (
        html.escape(value, quote=True).replace("`", "&#96;").replace("\r", " ").replace("\n", " ")
    )


def _markdown_text(value: str) -> str:
    return html.escape(value, quote=True).replace("\r", " ").replace("\n", " ")


def _validate_api_test_cases(
    cases: ApiTestCasesDraft,
    *,
    tool_results: list[dict[str, Any]],
    requirement_catalog: RequirementCatalog | None,
    source_bundle: SourceBundle,
) -> None:
    inspections = [
        item.get("result")
        for item in tool_results
        if item.get("tool") == "openapi.inspect" and isinstance(item.get("result"), dict)
    ]
    confirmed_endpoints: dict[tuple[str, str], set[str]] = {}
    for inspection in inspections:
        if inspection.get("contract_status") != "confirmed":
            continue
        source = str(inspection.get("source") or "")
        for endpoint in inspection.get("endpoints", []):
            if not isinstance(endpoint, dict):
                continue
            key = (
                str(endpoint.get("method") or "").upper(),
                str(endpoint.get("path") or ""),
            )
            confirmed_endpoints.setdefault(key, set()).add(source)
    known_rules = (
        {rule.rule_id for rule in requirement_catalog.rules}
        if requirement_catalog is not None
        else set()
    )
    frozen_sources = {document.path for document in source_bundle.documents}
    inspected_capture_sources = {
        catalog.source_path
        for catalog in _api_discovery_catalogs(
            tool_results,
            source_bundle=source_bundle,
        )
    }
    for case in cases.cases:
        if known_rules:
            unknown_rules = set(case.business_rule_refs) - known_rules
            if unknown_rules:
                raise ValueError(
                    f"{case.id} references unknown requirement rules: {sorted(unknown_rules)}"
                )
        capture_refs = {
            reference.source_path
            for reference in case.source_refs
            if reference.source_type == "playwright-network-capture"
        }
        uninspected_capture_refs = capture_refs - inspected_capture_sources
        if uninspected_capture_refs:
            raise ValueError(
                f"{case.id} references uninspected network captures: "
                f"{sorted(uninspected_capture_refs)}"
            )
        if case.contract_status != "confirmed":
            continue
        endpoint = (str(case.request.method or "").upper(), str(case.request.path or ""))
        sources = confirmed_endpoints.get(endpoint)
        if not sources:
            raise ValueError(
                f"{case.id} claims unverified endpoint {endpoint[0]} {endpoint[1]}; "
                "call openapi.inspect on a complete frozen contract first"
            )
        frozen_endpoint_sources = sources & frozen_sources
        if not frozen_endpoint_sources:
            raise ValueError(f"{case.id} endpoint sources are not part of the frozen SourceBundle")
        if not any(
            reference.source_type == "openapi"
            and reference.source_path in frozen_endpoint_sources
            and reference.confidence == "high"
            for reference in case.source_refs
        ):
            raise ValueError(
                f"{case.id} confirmed endpoint lacks a high-confidence reference to "
                f"one of {sorted(frozen_endpoint_sources)}"
            )


def _requirement_catalog_from_dependencies(
    dependencies: dict[str, dict[str, Any]],
) -> RequirementCatalog | None:
    catalogs = [
        AgentOutput.model_validate(value).requirement_catalog
        for value in dependencies.values()
        if isinstance(value, dict)
    ]
    present = [catalog for catalog in catalogs if catalog is not None]
    if not present:
        return None
    hashes = {catalog_hash(catalog) for catalog in present}
    if len(hashes) != 1:
        raise ValueError("dependencies contain conflicting RequirementCatalog values")
    return present[0]


def _risk_catalog_from_dependencies(
    dependencies: dict[str, dict[str, Any]],
) -> RiskCatalog | None:
    catalogs = [
        AgentOutput.model_validate(value).risk_catalog
        for value in dependencies.values()
        if isinstance(value, dict)
    ]
    present = [catalog for catalog in catalogs if catalog is not None]
    if not present:
        return None
    identities = {catalog.model_dump_json() for catalog in present}
    if len(identities) != 1:
        raise ValueError("dependencies contain conflicting RiskCatalog values")
    return present[0]


def _prompt_dependencies(
    dependencies: dict[str, dict[str, Any]],
    agent: str,
) -> dict[str, Any]:
    if agent not in {"risk_strategist", "test_designer"}:
        return sanitize_untrusted(dependencies)
    result: dict[str, Any] = {}
    for task_id, value in dependencies.items():
        output = AgentOutput.model_validate(value)
        result[task_id] = {
            "summary": output.summary,
            "evidence": output.evidence,
            "pending": output.pending,
            "has_requirement_catalog": output.requirement_catalog is not None,
            "has_risk_catalog": output.risk_catalog is not None,
        }
    return result


def _testcase_rule_batches(
    catalog: RequirementCatalog,
    risks: RiskCatalog | None,
    *,
    batch_size: int,
) -> list[dict[str, Any]]:
    if batch_size < 1:
        raise ValueError("testcase rule batch_size must be positive")
    risk_by_rule: dict[str, list[dict[str, Any]]] = {}
    for risk in risks.risks if risks is not None else []:
        payload = risk.model_dump(mode="json")
        for rule_id in risk.rule_ids:
            risk_by_rule.setdefault(rule_id, []).append(payload)
    batches: list[dict[str, Any]] = []
    for offset in range(0, len(catalog.rules), batch_size):
        rules = catalog.rules[offset : offset + batch_size]
        rule_ids = [rule.rule_id for rule in rules]
        batches.append(
            {
                "batch_id": f"rules-{len(batches) + 1:03d}",
                "rule_ids": rule_ids,
                "rules": [rule.model_dump(mode="json") for rule in rules],
                "risks": [risk for rule_id in rule_ids for risk in risk_by_rule.get(rule_id, [])],
            }
        )
    return batches


def _catalog_for_rule_ids(
    catalog: RequirementCatalog,
    rule_ids: set[str],
) -> RequirementCatalog:
    known = {rule.rule_id for rule in catalog.rules}
    unknown = rule_ids - known
    if unknown:
        raise ValueError(f"testcase batch references unknown rules: {sorted(unknown)}")
    rules = [rule for rule in catalog.rules if rule.rule_id in rule_ids]
    referenced_sources = {reference.source for rule in rules for reference in rule.source_refs}
    return catalog.model_copy(
        update={
            "sources": [
                reference for reference in catalog.sources if reference.source in referenced_sources
            ],
            "rules": rules,
        }
    )


def _merge_testcase_batches(
    catalog: RequirementCatalog,
    fragments: list[TestCaseSet],
) -> TestCaseSet:
    if not fragments:
        raise ValueError("testcase batch generation produced no fragments")
    merged = TestCaseSet(
        requirement_catalog_hash=catalog_hash(catalog),
        cases=[case for fragment in fragments for case in fragment.cases],
        coverage=[mapping for fragment in fragments for mapping in fragment.coverage],
    )
    issues = validate_testcase_set(catalog, merged)
    if issues:
        raise ValueError(
            "merged testcase batches failed validation: "
            + json.dumps(
                [item.model_dump(mode="json") for item in issues],
                ensure_ascii=False,
            )[:8000]
        )
    return merged


def _deterministic_testcase_batch_fallback(
    catalog: RequirementCatalog,
    risks: RiskCatalog,
) -> TestCaseSet:
    priority_order = {
        RiskLevel.P0: 0,
        RiskLevel.P1: 1,
        RiskLevel.P2: 2,
        RiskLevel.P3: 3,
    }
    cases: list[TestCase] = []
    coverage: list[CoverageMapping] = []
    for rule in catalog.rules:
        matching_priorities = [
            risk.priority for risk in risks.risks if rule.rule_id in risk.rule_ids
        ]
        priority = (
            min(matching_priorities, key=priority_order.__getitem__)
            if matching_priorities
            else RiskLevel.P2
        )
        case_id = f"TC-{rule.rule_id}-001"
        fallback_pending = (
            "模型批次修复耗尽；当前为规则驱动基础用例，具体测试数据和执行细节待人工补充。"
        )
        cases.append(
            TestCase(
                case_id=case_id,
                rule_ids=[rule.rule_id],
                title=f"验证：{rule.title}",
                test_type="规则验证",
                priority=priority,
                preconditions=[rule.condition],
                test_data=["满足规则条件的最小测试数据，具体取值待人工确认"],
                steps=[
                    f"准备满足“{rule.condition}”的业务场景",
                    f"执行与“{rule.title}”对应的业务操作",
                    "记录系统返回或界面展示的可观察结果",
                ],
                expected_results=[rule.outcome],
                assertions=[f"可观察结果应满足规则结果：{rule.outcome}"],
                pending_items=[*rule.pending_questions, fallback_pending],
                covered_boundary_values=[
                    value for boundary in rule.boundaries for value in boundary.values
                ],
                covered_transitions=rule.state_transitions,
            )
        )
        coverage.append(
            CoverageMapping(
                rule_id=rule.rule_id,
                case_ids=[case_id],
                rationale="规则驱动的确定性基础覆盖；数据和执行细节等待人工 Review。",
            )
        )
    return TestCaseSet(
        requirement_catalog_hash=catalog_hash(catalog),
        cases=cases,
        coverage=coverage,
    )


def _catalog_source_selection(
    catalog: RequirementCatalog,
    source_bundle: SourceBundle,
) -> list[dict[str, Any]]:
    hashes = {document.path: document.raw_sha256 for document in source_bundle.documents}
    references = {
        (
            reference.source,
            reference.chunk_id,
            reference.selection_reason or "rule_catalog_batch",
        )
        for rule in catalog.rules
        for reference in rule.source_refs
    }
    return [
        {
            "source": source,
            "raw_sha256": hashes.get(source),
            "chunk_id": chunk_id,
            "selection_reason": reason,
        }
        for source, chunk_id, reason in sorted(
            references,
            key=lambda item: (item[0], item[1] or "", item[2]),
        )
    ]


def _quality_blocker_scope(
    feedback: list[dict[str, str]],
) -> tuple[set[str], set[str]]:
    for item in reversed(feedback):
        if item.get("kind") != "quality_gate":
            continue
        try:
            payload = json.loads(item.get("error") or "{}")
        except json.JSONDecodeError:
            return set(), set()
        blockers = [blocker for blocker in payload.get("blockers", []) if isinstance(blocker, dict)]
        return (
            {str(blocker["case_id"]) for blocker in blockers if blocker.get("case_id")},
            {str(blocker["rule_id"]) for blocker in blockers if blocker.get("rule_id")},
        )
    return set(), set()


def _targeted_testcase_patch_context(
    current: TestCaseSet,
    feedback: list[dict[str, str]],
) -> tuple[TestCaseSet, set[str]] | None:
    allowed_case_ids, allowed_rule_ids = _quality_blocker_scope(feedback)
    if not allowed_case_ids and not allowed_rule_ids:
        return None
    selected_cases = [
        case
        for case in current.cases
        if case.case_id in allowed_case_ids or set(case.rule_ids) & allowed_rule_ids
    ]
    if not selected_cases:
        return None
    selected_case_ids = {case.case_id for case in selected_cases}
    selected_rule_ids = {
        rule_id for case in selected_cases for rule_id in case.rule_ids
    } | allowed_rule_ids
    selected_coverage = []
    for mapping in current.coverage:
        case_ids = [case_id for case_id in mapping.case_ids if case_id in selected_case_ids]
        if case_ids:
            selected_coverage.append(mapping.model_copy(update={"case_ids": case_ids}))
    if not selected_coverage:
        return None
    return (
        current.model_copy(
            update={
                "cases": selected_cases,
                "coverage": selected_coverage,
            }
        ),
        selected_rule_ids,
    )


def _validate_targeted_testcase_patch(
    patch: TestCasePatch,
    current: TestCaseSet,
    feedback: list[dict[str, str]],
) -> None:
    allowed_case_ids, allowed_rule_ids = _quality_blocker_scope(feedback)
    if not allowed_case_ids and not allowed_rule_ids:
        return
    current_by_id = {case.case_id: case for case in current.cases}

    def case_is_targeted(case_id: str, rule_ids: list[str]) -> bool:
        existing = current_by_id.get(case_id)
        effective_rules = set(rule_ids) | (
            set(existing.rule_ids) if existing is not None else set()
        )
        return case_id in allowed_case_ids or bool(effective_rules & allowed_rule_ids)

    unrelated_cases = {
        case.case_id
        for case in patch.replace_cases
        if not case_is_targeted(case.case_id, case.rule_ids)
    }
    unrelated_cases.update(
        case_id for case_id in patch.remove_case_ids if not case_is_targeted(case_id, [])
    )
    unrelated_rules = {
        mapping.rule_id
        for mapping in patch.replace_coverage
        if mapping.rule_id not in allowed_rule_ids and not set(mapping.case_ids) & allowed_case_ids
    }
    if unrelated_cases or unrelated_rules:
        raise ValueError(
            "TestCasePatch modifies content outside reviewer blocker scope: "
            f"cases={sorted(unrelated_cases)}, rules={sorted(unrelated_rules)}"
        )


def _validate_catalog_sources(
    catalog: RequirementCatalog,
    source_bundle: SourceBundle,
) -> None:
    known_sources = {document.path for document in source_bundle.documents} | {"user_goal"}
    unknown = {
        reference.source
        for reference in [
            *catalog.sources,
            *(reference for rule in catalog.rules for reference in rule.source_refs),
        ]
        if reference.source not in known_sources
    }
    if unknown:
        raise ValueError(
            f"RequirementCatalog references sources outside the frozen SourceBundle: "
            f"{sorted(unknown)}"
        )


def _validate_catalog_merge(
    fragments: list[RequirementCatalog],
    merged: RequirementCatalog,
) -> None:
    if not fragments:
        return
    expected_rule_ids = {rule.rule_id for fragment in fragments for rule in fragment.rules}
    merged_rules = {rule.rule_id: rule for rule in merged.rules}
    missing_rules = expected_rule_ids - set(merged_rules)
    if missing_rules:
        raise ValueError(f"merged RequirementCatalog omitted source rules: {sorted(missing_rules)}")
    for rule_id in expected_rule_ids:
        confirmed_fragments = [
            rule
            for fragment in fragments
            for rule in fragment.rules
            if rule.rule_id == rule_id and rule.evidence_level == EvidenceLevel.CONFIRMED
        ]
        if not confirmed_fragments:
            continue
        expected_sources = {
            reference.source for rule in confirmed_fragments for reference in rule.source_refs
        }
        actual_sources = {reference.source for reference in merged_rules[rule_id].source_refs}
        if not expected_sources.issubset(actual_sources):
            raise ValueError(
                f"merged rule {rule_id} lost source refs: "
                f"{sorted(expected_sources - actual_sources)}"
            )


def _generation_source_selection(
    tool_results: list[dict[str, Any]],
    source_bundle: SourceBundle,
) -> list[dict[str, Any]]:
    hashes = {document.path: document.raw_sha256 for document in source_bundle.documents}
    selected: dict[tuple[str, str | None], dict[str, Any]] = {}
    for record in tool_results:
        tool = record.get("tool")
        result = record.get("result")
        if not isinstance(result, dict):
            continue
        if tool == "workspace.read":
            source = str(result.get("path") or "")
            if source:
                selected[(source, None)] = {
                    "source": source,
                    "raw_sha256": hashes.get(source),
                    "selection_reason": "workspace.read",
                }
        elif tool == "rag.retrieve":
            for chunk in result.get("chunks") or []:
                if not isinstance(chunk, dict):
                    continue
                source = str(chunk.get("source") or "")
                chunk_id = str(chunk.get("chunk_id") or "") or None
                if source:
                    selected[(source, chunk_id)] = {
                        "source": source,
                        "raw_sha256": hashes.get(source),
                        "chunk_id": chunk_id,
                        "selection_reason": str(chunk.get("selection_reason") or "rag.retrieve"),
                    }
        elif tool == "openapi.inspect":
            source = str(result.get("source") or "")
            if source:
                selected[(source, None)] = {
                    "source": source,
                    "raw_sha256": hashes.get(source),
                    "selection_reason": "openapi.inspect",
                }
        elif tool == "network.capture.inspect":
            source = str(result.get("source_path") or "")
            if source:
                selected[(source, None)] = {
                    "source": source,
                    "raw_sha256": hashes.get(source),
                    "selection_reason": "network.capture.inspect",
                }
        elif tool == "network.capture.live":
            source = str(result.get("source_path") or "")
            if source:
                selected[(source, None)] = {
                    "source": source,
                    "raw_sha256": None,
                    "selection_reason": "network.capture.live",
                }
    return list(selected.values())


def _ready_task_ids(plan: QAPlan, pending: list[str], completed: list[str]) -> list[str]:
    pending_set = set(pending)
    completed_set = set(completed)
    return [
        task.id
        for task in plan.tasks
        if task.id in pending_set and set(task.dependencies).issubset(completed_set)
    ]


def _tool_key(
    run_id: str,
    task_id: str,
    step: int,
    tool: str,
    arguments: dict[str, Any],
) -> str:
    payload = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"{run_id}:{task_id}:{step}:{tool}:{digest}"
