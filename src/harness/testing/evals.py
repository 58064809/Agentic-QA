from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from harness.contracts import (
    ArtifactVariant,
    CreateWorkspaceCommand,
    ExecutionProfile,
    ReviewDecision,
    ReviewRunCommand,
    StartRunCommand,
)
from harness.domain.models import ARTIFACT_TYPES
from harness.domain.schemas.qa_design import RiskCatalog, RiskItem, SourceReference
from harness.harness import Harness
from harness.infrastructure.llm.gateway import CallableModelGateway
from harness.infrastructure.mcp.playwright import MCPBridge, MCPToolSnapshot
from harness.infrastructure.workflow.engine import (
    ARTIFACT_AGENT,
    AgentOutput,
    build_default_plan,
    default_recorded_artifact,
    default_recorded_requirement_catalog,
)


class _EvalCheckpointProvider:
    def __init__(self) -> None:
        self._checkpointer = InMemorySaver()

    @contextmanager
    def open(self):
        yield self._checkpointer


def recorded_model_gateway(*, use_fake_mcp: bool = False) -> CallableModelGateway:
    def respond(
        *,
        prompt: str,
        response_model: type,
        tools: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if response_model.__name__ == "QAPlan":
            request = StartRunCommand.model_validate_json(prompt.splitlines()[-1])
            return build_default_plan(request).model_dump(mode="json")
        if response_model is AgentOutput:
            context = json.loads(prompt)
            outputs = context["task"]["expected_outputs"]
            agent = context["task"]["agent"]
            allowed_tools = {item["name"] for item in tools}
            if (
                use_fake_mcp
                and "mcp.playwright" in allowed_tools
                and not context.get("tool_results")
            ):
                return {
                    "summary": "recorded Playwright request",
                    "artifacts": {},
                    "evidence": [],
                    "pending": [],
                    "tool_requests": [
                        {
                            "tool": "mcp.playwright",
                            "arguments": {
                                "tool": "browser_snapshot",
                                "arguments": {},
                            },
                        }
                    ],
                }
            payload: dict[str, Any] = {
                "summary": "recorded expert response",
                "artifacts": {
                    artifact: default_recorded_artifact(artifact, context["goal"])
                    for artifact in outputs
                    if artifact in ARTIFACT_AGENT
                    and agent not in {"requirement_analyst", "test_designer"}
                },
                "evidence": context.get("source_files")
                or [str(context.get("source", {}).get("path") or "user_goal")],
                "pending": [],
                "tool_requests": [],
            }
            if agent == "requirement_analyst":
                payload["artifacts"] = {}
                catalog = default_recorded_requirement_catalog(context["goal"])
                source_path = str(context.get("source", {}).get("path") or "")
                if source_path:
                    raw_sha256 = str(context.get("source", {}).get("raw_sha256") or "")
                    source_rule_id = f"SRC-{raw_sha256.removeprefix('sha256:')[:8].upper()}-001"
                    reference = SourceReference(
                        source=source_path,
                        section="recorded source fragment",
                    )
                    catalog = catalog.model_copy(
                        update={
                            "sources": [reference],
                            "rules": [
                                rule.model_copy(
                                    update={
                                        "rule_id": source_rule_id,
                                        "source_refs": [reference],
                                    }
                                )
                                for rule in catalog.rules
                            ],
                        }
                    )
                elif context.get("source_fragments"):
                    fragments = [
                        type(catalog).model_validate(item) for item in context["source_fragments"]
                    ]
                    catalog = fragments[0]
                    sources = {
                        (reference.source, reference.section): reference
                        for fragment in fragments
                        for reference in fragment.sources
                    }
                    rules = {}
                    for fragment in fragments:
                        for rule in fragment.rules:
                            existing = rules.get(rule.rule_id)
                            if existing is None:
                                rules[rule.rule_id] = rule
                                continue
                            refs = {
                                (reference.source, reference.section): reference
                                for reference in [
                                    *existing.source_refs,
                                    *rule.source_refs,
                                ]
                            }
                            rules[rule.rule_id] = existing.model_copy(
                                update={"source_refs": list(refs.values())}
                            )
                    catalog = catalog.model_copy(
                        update={
                            "sources": list(sources.values()),
                            "rules": list(rules.values()),
                        }
                    )
                payload["requirement_catalog"] = catalog.model_dump(mode="json")
            elif agent == "risk_strategist":
                rule_ids = [
                    rule["rule_id"]
                    for rule in (context.get("requirement_catalog") or {}).get("rules", [])
                ] or ["GOAL-001"]
                payload["risk_catalog"] = RiskCatalog(
                    risks=[
                        RiskItem(
                            risk_id=f"RISK-{index:03d}",
                            title="用户目标未被验证",
                            rule_ids=[rule_id],
                            priority="P1",
                            rationale="遗漏主流程会使目标无法验收",
                            coverage_intent=["覆盖用户目标主流程并保留可观察证据"],
                        )
                        for index, rule_id in enumerate(rule_ids, 1)
                    ]
                ).model_dump(mode="json")
            elif agent == "test_designer":
                payload["artifacts"] = {}
                current = context.get("current_testcase_set")
                if current is not None:
                    payload["testcase_patch"] = {
                        "schema_version": "agentic-qa.test-case-patch.v1",
                        "replace_cases": [],
                        "remove_case_ids": [],
                        "replace_coverage": [
                            {
                                **mapping,
                                "rationale": "直接覆盖结构化需求规则",
                            }
                            for mapping in current.get("coverage", [])
                        ],
                    }
                    return payload
                rule_ids = [
                    rule["rule_id"]
                    for rule in (context.get("requirement_catalog") or {}).get("rules", [])
                ] or ["GOAL-001"]
                payload["testcase_set"] = {
                    "schema_version": "agentic-qa.test-case-set.v1",
                    "cases": [
                        {
                            "case_id": f"TC-{rule_id}",
                            "rule_ids": [rule_id],
                            "title": f"验证规则 {rule_id}",
                            "test_type": "功能",
                            "priority": "P1",
                            "preconditions": ["已准备隔离的测试环境"],
                            "test_data": ["使用脱敏且可重复的测试数据"],
                            "steps": ["执行规则对应的业务流程", "记录可观察结果"],
                            "expected_results": [f"可观察结果满足规则 {rule_id}"],
                            "assertions": ["保存业务输出或状态作为审核证据"],
                            "pending_items": ["具体环境与观察点需人工确认"],
                            "covered_boundary_values": [],
                            "covered_transitions": [],
                        }
                        for rule_id in rule_ids
                    ],
                    "coverage": [
                        {
                            "rule_id": rule_id,
                            "case_ids": [f"TC-{rule_id}"],
                            "rationale": "直接覆盖结构化需求规则",
                        }
                        for rule_id in rule_ids
                    ],
                }
            return payload
        raise AssertionError(f"unexpected response model: {response_model}")

    return CallableModelGateway(respond)


def run_offline_eval() -> dict[str, Any]:
    """Deterministic no-network scenario covering all first-release artifact routes."""
    with TemporaryDirectory(prefix="agentic-qa-eval-") as temporary:
        workspace_id = Path(temporary).name
        mcp_calls = 0

        def fake_playwright(_name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
            nonlocal mcp_calls
            mcp_calls += 1
            return {"page": "recorded", "elements": []}

        bridge = MCPBridge(
            MCPToolSnapshot.freeze(
                server="playwright",
                transport="stdio",
                listed_tools=[
                    {
                        "name": "browser_snapshot",
                        "inputSchema": {
                            "type": "object",
                            "additionalProperties": False,
                        },
                    }
                ],
                allowlist={"browser_snapshot"},
            ),
            fake_playwright,
        )
        harness = Harness(
            Path(temporary),
            model_gateway=recorded_model_gateway(use_fake_mcp=True),
            checkpoint_provider=_EvalCheckpointProvider(),
            tool_handlers={"mcp.playwright": bridge.tool_handler},
        )
        workspace = harness.create_workspace(
            CreateWorkspaceCommand(
                workspace_id=workspace_id,
                quality_policies=[],
            )
        )
        (workspace / "sources/eval-scope.md").write_text(
            "# 离线评测范围\n\n本来源仅用于验证完整的候选、审核和发布链路。\n",
            encoding="utf-8",
        )
        workspace.joinpath("workspace.yml").write_text(
            f"""schema_version: agentic-qa.harness.workspace.v2
id: {workspace_id}
quality_policies: []
execution:
  environments:
    recorded-test:
      allow_ui_mutations: true
      max_request_timeout_seconds: 10
""",
            encoding="utf-8",
        )
        snapshot = harness.start_run(
            StartRunCommand(
                workspace_id=workspace_id,
                goal="离线评测：覆盖需求、设计、API、UI、执行、分诊和报告闭环",
                expected_artifacts=list(ARTIFACT_TYPES),
                execution_profile=ExecutionProfile(
                    environment="recorded-test",
                    allow_ui_mutations=True,
                ),
            )
        )
        candidate_types = {candidate.artifact for candidate in snapshot.candidates}
        generated = candidate_types == set(ARTIFACT_TYPES)
        gate_held = snapshot.status == "needs_human_review"
        published = harness.review_run(
            ReviewRunCommand(
                workspace_id=workspace_id,
                run_id=snapshot.run_id,
                decision=ReviewDecision(
                    intent="approve",
                    target_artifact="all",
                    reason="offline deterministic eval",
                    reviewed_by="recorded_qa_owner",
                    versions=[
                        candidate.version_ref(ArtifactVariant.RAW)
                        for candidate in snapshot.candidates
                    ],
                ),
            ),
        )
        checks = {
            "all_artifact_routes": generated,
            "review_gate_interrupt": gate_held,
            "fake_playwright_mcp": mcp_calls == 2,
            "mcp_snapshot_frozen": any(
                item.get("schema_version") == "agentic-qa.harness.mcp-tool-snapshot.v2"
                for item in snapshot.tool_calls
            ),
            "deterministic_promote": published.status == "published",
        }
        return {
            "schema_version": "agentic-qa.harness.eval-result.v2",
            "passed": all(checks.values()),
            "checks": checks,
            "artifact_count": len(candidate_types),
        }


def run_eval() -> dict[str, Any]:
    from harness.testing.golden import run_golden_eval

    workflow = run_offline_eval()
    golden = run_golden_eval()
    return {
        "schema_version": "agentic-qa.harness.eval-suite-result.v1",
        "passed": workflow["passed"] and golden["passed"],
        "workflow": workflow,
        "golden": golden,
    }


def run_live_eval() -> dict[str, Any]:
    from harness.infrastructure.llm.gateway import model_gateway_from_env
    from harness.testing.golden import evaluate_candidate_artifacts

    gateway = model_gateway_from_env()
    if gateway is None:
        raise RuntimeError("live eval requires an explicitly configured model API key")
    with TemporaryDirectory(prefix="agentic-qa-live-eval-") as temporary:
        harness = Harness(
            Path(temporary),
            model_gateway=gateway,
            checkpoint_provider=_EvalCheckpointProvider(),
        )
        workspace = harness.create_workspace(
            CreateWorkspaceCommand(workspace_id="nightly-live-eval")
        )
        working_case = Path.cwd() / "evals" / "cases" / "login-lock"
        packaged_case = Path(__file__).resolve().parents[3] / "evals" / "cases" / "login-lock"
        case_root = working_case if working_case.is_dir() else packaged_case
        if not case_root.is_dir():
            raise FileNotFoundError("login-lock live eval case is unavailable")
        (workspace / "sources/login-lock.md").write_text(
            (case_root / "source.md").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        snapshot = harness.start_run(
            StartRunCommand(
                workspace_id="nightly-live-eval",
                goal="生成可追踪的登录锁定需求目录和边界/状态测试用例",
                expected_artifacts=["requirement_analysis", "testcases"],
            )
        )
        raw_artifacts: dict[str, str] = {}
        for candidate in snapshot.candidates:
            raw_version = next(
                (
                    version
                    for version in candidate.versions
                    if version.variant == ArtifactVariant.RAW
                ),
                None,
            )
            if raw_version is not None:
                raw_artifacts[candidate.artifact] = (Path(temporary) / raw_version.path).read_text(
                    encoding="utf-8"
                )
        golden = None
        if {"requirement_analysis", "testcases"}.issubset(raw_artifacts):
            golden = evaluate_candidate_artifacts(
                case_root,
                requirement_content=raw_artifacts["requirement_analysis"],
                testcase_content=raw_artifacts["testcases"],
            )
        structurally_complete = snapshot.status == "needs_human_review" and all(
            not candidate.partial for candidate in snapshot.candidates
        )
        result = {
            "schema_version": "agentic-qa.harness.live-eval-result.v1",
            "passed": structurally_complete and golden is not None and golden["passed"],
            "status": snapshot.status,
            "candidate_count": len(snapshot.candidates),
            "errors": snapshot.errors,
            "model_usage": snapshot.model_usage,
            "golden": golden,
        }
        output_root = os.getenv("AGENTIC_QA_LIVE_EVAL_OUTPUT", "").strip()
        if output_root:
            _export_live_eval_artifacts(
                repo_root=Path(temporary),
                workspace=workspace,
                snapshot=snapshot,
                output_root=Path(output_root),
            )
        return result


def _export_live_eval_artifacts(
    *,
    repo_root: Path,
    workspace: Path,
    snapshot: Any,
    output_root: Path,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    source_bundle = workspace / "runs" / snapshot.run_id / "source-bundle.json"
    if source_bundle.is_file():
        copyfile(source_bundle, output_root / "source-bundle.json")
    for candidate in snapshot.candidates:
        artifact_root = output_root / candidate.artifact
        artifact_root.mkdir(parents=True, exist_ok=True)
        raw_version = next(
            (version for version in candidate.versions if version.variant == ArtifactVariant.RAW),
            None,
        )
        if raw_version is not None:
            copyfile(repo_root / raw_version.path, artifact_root / "raw.md")
        for source_path, output_name in (
            (candidate.quality_report_path, "quality-report.json"),
            (candidate.generation_report_path, "generation-report.json"),
        ):
            if source_path:
                copyfile(repo_root / source_path, artifact_root / output_name)
