from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path
from shutil import copyfile, copytree, ignore_patterns
from tempfile import TemporaryDirectory
from typing import Any

import yaml
from langgraph.checkpoint.memory import InMemorySaver

from harness.contracts import (
    ApiScenarioPrepareCommand,
    ArtifactVariant,
    CreateWorkspaceCommand,
    ExecutionProfile,
    ReviewDecision,
    ReviewRunCommand,
    RunRef,
    StartRunCommand,
)
from harness.domain.models import ARTIFACT_TYPES
from harness.domain.schemas.api_test_cases import SourceRef as ApiSourceRef
from harness.domain.schemas.qa_design import RiskCatalog, RiskItem, SourceReference
from harness.harness import Harness
from harness.infrastructure.llm.gateway import CallableModelGateway
from harness.infrastructure.mcp.playwright import MCPBridge, MCPToolSnapshot
from harness.infrastructure.workflow.engine import (
    ARTIFACT_AGENT,
    AgentOutput,
    build_default_plan,
    default_recorded_api_test_cases,
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
        envelope = json.loads(prompt)
        context = {
            **envelope.get("trusted_context", {}),
            **envelope.get("untrusted_context", {}),
        }
        if response_model.__name__ == "QAPlan":
            request = StartRunCommand(
                workspace_id="recorded-eval",
                goal=context["goal"],
                expected_artifacts=context["expected_artifacts"],
            )
            return build_default_plan(request).model_dump(mode="json")
        if response_model is AgentOutput:
            outputs = context["task"]["expected_outputs"]
            agent = context["task"]["agent"]
            allowed_tools = {item["name"] for item in tools}
            playwright_tools = {
                name for name in allowed_tools if name.startswith("mcp.playwright.")
            }
            if (
                agent == "api_test_engineer"
                and "api_discovery_report" in outputs
                and "network.capture.inspect" in allowed_tools
                and not context.get("tool_results")
            ):
                capture_sources = [
                    source
                    for source in context.get("source_files", [])
                    if source.casefold().endswith((".har", ".json"))
                    and (
                        "capture" in source.casefold()
                        or "network" in source.casefold()
                        or source.casefold().endswith(".har")
                    )
                ]
                if capture_sources:
                    return {
                        "summary": "recorded network capture inspection request",
                        "artifacts": {},
                        "evidence": [],
                        "pending": [],
                        "tool_requests": [
                            {
                                "tool": "network.capture.inspect",
                                "arguments": {"path": capture_sources[0]},
                            }
                        ],
                    }
            if (
                agent == "api_test_engineer"
                and "api_discovery_report" in outputs
                and "network.capture.live" in allowed_tools
                and playwright_tools
            ):
                tool_results = context.get("tool_results") or []
                used_tools = {
                    str(item.get("tool") or "") for item in tool_results if isinstance(item, dict)
                }
                if "mcp.playwright" not in used_tools:
                    navigate_tool = next(
                        name for name in playwright_tools if name.endswith(".browser_navigate")
                    )
                    return {
                        "summary": "recorded live Playwright navigation request",
                        "artifacts": {},
                        "evidence": [],
                        "pending": [],
                        "tool_requests": [
                            {
                                "tool": navigate_tool,
                                "arguments": {"url": context["test_base_url"]},
                            }
                        ],
                    }
                if "network.capture.live" not in used_tools:
                    return {
                        "summary": "recorded live Playwright network capture request",
                        "artifacts": {},
                        "evidence": [],
                        "pending": [],
                        "tool_requests": [
                            {
                                "tool": "network.capture.live",
                                "arguments": {"max_requests": 25},
                            }
                        ],
                    }
            if use_fake_mcp and playwright_tools and not context.get("tool_results"):
                snapshot_tool = next(
                    name for name in playwright_tools if name.endswith(".browser_snapshot")
                )
                return {
                    "summary": "recorded Playwright request",
                    "artifacts": {},
                    "evidence": [],
                    "pending": [],
                    "tool_requests": [
                        {
                            "tool": snapshot_tool,
                            "arguments": {},
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
                or [str(context.get("source_identity", {}).get("path") or "user_goal")],
                "pending": [],
                "tool_requests": [],
            }
            if agent == "api_test_engineer" and "api_test_draft" in outputs:
                payload["artifacts"].pop("api_test_draft", None)
                draft = default_recorded_api_test_cases(context["goal"])
                rule_ids = [
                    rule["rule_id"]
                    for rule in (context.get("requirement_catalog") or {}).get("rules", [])
                ] or ["GOAL-001"]
                draft = draft.model_copy(
                    update={
                        "business_rules": rule_ids,
                        "cases": [
                            case.model_copy(update={"business_rule_refs": rule_ids})
                            for case in draft.cases
                        ],
                    }
                )
                manual_inspection = next(
                    (
                        item.get("result")
                        for item in context.get("tool_results", [])
                        if item.get("tool") == "manual-test-cases.inspect"
                    ),
                    None,
                )
                if isinstance(manual_inspection, dict):
                    manual_refs = [
                        ApiSourceRef(
                            source_type="manual-test-case",
                            source_path=str(item["source_path"]),
                            chunk_id=str(item["case_id"]),
                            locator=f"case_id={item['case_id']}",
                            summary=str(item["title"]),
                            confidence="high",
                        )
                        for item in manual_inspection.get("cases", [])
                        if isinstance(item, dict)
                    ]
                    draft = draft.model_copy(
                        update={
                            "source_refs": [*draft.source_refs, *manual_refs],
                            "cases": [
                                case.model_copy(update={"source_refs": manual_refs})
                                for case in draft.cases
                            ],
                        }
                    )
                payload["api_test_cases"] = draft.model_dump(mode="json")
            if agent == "requirement_analyst":
                payload["artifacts"] = {}
                catalog = default_recorded_requirement_catalog(context["goal"])
                source_path = str(context.get("source_identity", {}).get("path") or "")
                if source_path:
                    raw_sha256 = str(context.get("source_identity", {}).get("raw_sha256") or "")
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
    """Deterministic no-network scenario covering guarded workflow routes."""
    from harness.infrastructure.local_config import FilesystemLocalConfigLoader

    project_config = FilesystemLocalConfigLoader(Path.cwd()).load_required()
    with TemporaryDirectory(prefix="agentic-qa-eval-") as temporary:
        temporary_root = Path(temporary)
        workspace_id = temporary_root.name
        eval_source = temporary_root / "local-sources" / "api" / "offline-eval"
        eval_source.mkdir(parents=True)
        (temporary_root / "agentic-qa.local.yml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": "agentic-qa.local-config.v1",
                    "model": project_config.model.model_dump(mode="json"),
                    "rag": {"provider": "local-lexical"},
                    "postgres": {
                        "host": "localhost",
                        "port": 5432,
                        "database": "postgres",
                        "user": "postgres",
                        "password": "offline-eval-only",
                    },
                    "test_management": {"provider": "none"},
                    "workspace_defaults": {},
                    "api": {
                        "services": {
                            "offline-eval": {
                                "source_directory": "local-sources/api/offline-eval",
                                "environments": {
                                    "recorded-test": {
                                        "base_url": "https://qa.example.test",
                                        "trusted_origins": ["https://qa.example.test"],
                                        "allowed_http_methods": ["GET", "HEAD", "OPTIONS", "POST"],
                                        "auth": {"fallback_token": "offline-eval-token"},
                                    }
                                },
                            }
                        }
                    },
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        FilesystemLocalConfigLoader(temporary_root).migrate_inline_secrets()
        mcp_calls: list[str] = []

        def fake_playwright(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            mcp_calls.append(name)
            if name == "browser_network_requests":
                text = (
                    "### Result\n"
                    "1. [GET] https://qa.example.test/ => [200]\n"
                    "2. [POST] https://qa.example.test/api/eval => [200]"
                )
            elif name == "browser_network_request" and arguments.get("index") == 1:
                text = (
                    "### Result\n#1 [GET] https://qa.example.test/\n\n"
                    "  General\n"
                    "    status: [200]\n"
                    "    type: document\n"
                )
            elif name == "browser_network_request" and arguments.get("part"):
                text = '### Result\n{"token":"recorded-secret","ok":true}'
            elif name == "browser_network_request":
                text = (
                    "### Result\n#2 [POST] https://qa.example.test/api/eval\n\n"
                    "  General\n"
                    "    status: [200]\n"
                    "    duration: 12ms\n"
                    "    type: xhr\n"
                    "    mimeType: application/json\n\n"
                    "  Request headers\n"
                    "    content-type: application/json\n"
                    "    authorization: Bearer recorded-secret\n\n"
                    "  Response headers\n"
                    "    content-type: application/json\n"
                )
            else:
                text = "### Result\nrecorded Playwright action"
            return {"content": [{"type": "text", "text": text}], "isError": False}

        listed_tools = [
            {
                "name": "browser_snapshot",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                },
            },
            {
                "name": "browser_navigate",
                "inputSchema": {
                    "type": "object",
                    "required": ["url"],
                    "properties": {"url": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
            {
                "name": "browser_network_requests",
                "inputSchema": {
                    "type": "object",
                    "required": ["static"],
                    "properties": {"static": {"type": "boolean"}},
                    "additionalProperties": False,
                },
            },
            {
                "name": "browser_network_request",
                "inputSchema": {
                    "type": "object",
                    "required": ["index"],
                    "properties": {
                        "index": {"type": "integer"},
                        "part": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        ]
        bridge = MCPBridge(
            MCPToolSnapshot.freeze(
                server="playwright",
                transport="stdio",
                listed_tools=listed_tools,
                allowlist={item["name"] for item in listed_tools},
            ),
            fake_playwright,
        )
        harness = Harness(
            temporary_root,
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
        (workspace / "sources/network-capture.json").write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "method": "POST",
                            "url": "https://example.test/api/eval",
                            "status": 200,
                            "resource_type": "xhr",
                            "request_headers": {"Authorization": "Bearer recorded-secret"},
                            "request_body": {"case_id": "recorded", "token": "recorded-secret"},
                            "response_body": {"ok": True},
                            "duration_ms": 12,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        workspace.joinpath("workspace.yml").write_text(
            f"""schema_version: agentic-qa.harness.workspace.v2
id: {workspace_id}
quality_policies: []
execution:
  environments:
    recorded-test:
      base_url_env: LOCAL_OFFLINE_EVAL_RECORDED_TEST_BASE_URL
      trusted_origins: [https://qa.example.test]
      allowed_http_methods: [GET, HEAD, OPTIONS, POST]
      allow_ui_mutations: true
      max_request_timeout_seconds: 10
""",
            encoding="utf-8",
        )
        workflow_artifacts = [
            artifact for artifact in ARTIFACT_TYPES if artifact != "api_test_draft"
        ]
        snapshot = harness.start_run(
            StartRunCommand(
                workspace_id=workspace_id,
                goal="离线评测：覆盖需求、设计、API、UI、执行、分诊和报告闭环",
                expected_artifacts=workflow_artifacts,
                execution_profile=ExecutionProfile(
                    environment="recorded-test",
                    base_url_env="LOCAL_OFFLINE_EVAL_RECORDED_TEST_BASE_URL",
                    allowed_http_methods=["GET", "HEAD", "OPTIONS", "POST"],
                    allow_ui_mutations=True,
                ),
            )
        )
        candidate_types = {candidate.artifact for candidate in snapshot.candidates}
        generated = candidate_types == set(workflow_artifacts)
        try:
            harness.start_run(
                StartRunCommand(
                    workspace_id=workspace_id,
                    goal="离线评测：验证 API 生成入口不能绕过项目预检",
                    expected_artifacts=["api_test_draft"],
                )
            )
        except ValueError as exc:
            api_direct_entry_blocked = "use api prepare" in str(exc)
        else:
            api_direct_entry_blocked = False
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
        live_workspace_id = f"{workspace_id}-live"
        live_workspace = harness.create_workspace(
            CreateWorkspaceCommand(workspace_id=live_workspace_id)
        )
        live_workspace.joinpath("workspace.yml").write_text(
            f"""schema_version: agentic-qa.harness.workspace.v2
id: {live_workspace_id}
quality_policies: []
execution:
  environments:
    recorded-test:
      base_url_env: LOCAL_OFFLINE_EVAL_RECORDED_TEST_BASE_URL
      trusted_origins: [https://qa.example.test]
      allowed_http_methods: [GET, HEAD, OPTIONS, POST]
      allow_ui_mutations: true
      max_request_timeout_seconds: 10
""",
            encoding="utf-8",
        )
        live_snapshot = harness.start_run(
            StartRunCommand(
                workspace_id=live_workspace_id,
                goal="离线评测：模拟实时 Playwright 接口发现",
                expected_artifacts=["api_discovery_report"],
                execution_profile=ExecutionProfile(
                    environment="recorded-test",
                    base_url_env="LOCAL_OFFLINE_EVAL_RECORDED_TEST_BASE_URL",
                    allowed_http_methods=["GET", "HEAD", "OPTIONS", "POST"],
                    allow_ui_mutations=True,
                ),
            )
        )
        live_report = (Path(temporary) / live_snapshot.candidates[0].path).read_text(
            encoding="utf-8"
        )
        checks = {
            "all_artifact_routes": generated,
            "api_direct_entry_blocked": api_direct_entry_blocked,
            "review_gate_interrupt": gate_held,
            "fake_playwright_mcp": mcp_calls.count("browser_snapshot") == 2,
            "mcp_snapshot_frozen": any(
                item.get("schema_version") == "agentic-qa.harness.mcp-tool-snapshot.v2"
                for item in snapshot.tool_calls
            ),
            "live_api_discovery": (
                live_snapshot.status == "needs_human_review"
                and mcp_calls.count("browser_navigate") == 1
                and mcp_calls.count("browser_network_requests") == 1
                and "playwright_mcp" in live_report
                and "recorded-secret" not in live_report
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


def run_live_eval(
    case_name: str | None = None,
    *,
    output_root: Path | None = None,
    model_gateway: Any | None = None,
) -> dict[str, Any]:
    from harness.infrastructure.llm.gateway import model_gateway_from_config
    from harness.infrastructure.local_config import FilesystemLocalConfigLoader
    from harness.testing.golden import (
        evaluate_api_candidate_artifact,
        evaluate_candidate_artifacts,
    )

    project_config = FilesystemLocalConfigLoader(Path.cwd()).load_required()
    gateway = model_gateway or model_gateway_from_config(project_config.model)
    selected_case = case_name or "login-lock"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", selected_case):
        raise ValueError("live eval case must be a lowercase kebab-case name")
    with TemporaryDirectory(prefix="agentic-qa-live-eval-") as temporary:
        roots = [
            Path.cwd() / "evals" / "cases" / selected_case,
            Path.cwd() / "evals" / "api-cases" / selected_case,
            Path(__file__).resolve().parents[3] / "evals" / "cases" / selected_case,
            Path(__file__).resolve().parents[3] / "evals" / "api-cases" / selected_case,
        ]
        case_root = next((path for path in roots if path.is_dir()), roots[0])
        if not case_root.is_dir():
            raise FileNotFoundError(f"{selected_case} live eval case is unavailable")
        is_api_case = (case_root / "api-expectations.json").is_file()
        temporary_root = Path(temporary)
        eval_source = temporary_root / "local-sources" / "api" / selected_case
        if is_api_case:
            copytree(case_root, eval_source, ignore=ignore_patterns("api-test.yml"))
        local_payload: dict[str, Any] = {
            "schema_version": "agentic-qa.local-config.v1",
            "model": project_config.model.model_dump(mode="json"),
            "rag": {"provider": "local-lexical"},
            "postgres": {
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "live-eval-only",
            },
            "test_management": {"provider": "none"},
            "workspace_defaults": {},
            "api": {"services": {}},
        }
        if is_api_case:
            local_payload["api"] = {
                "services": {
                    selected_case: {
                        "source_directory": f"local-sources/api/{selected_case}",
                        "environments": {
                            "recorded-test": {
                                "base_url": "https://qa.example.test",
                                "trusted_origins": ["https://qa.example.test"],
                                "allowed_http_methods": ["GET", "POST", "DELETE"],
                                "auth": {"fallback_token": "recorded-eval-token"},
                            }
                        },
                    }
                }
            }
        (temporary_root / "agentic-qa.local.yml").write_text(
            yaml.safe_dump(local_payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        FilesystemLocalConfigLoader(temporary_root).migrate_inline_secrets()
        goal_path = case_root / "live-goal.txt"
        goal = (
            goal_path.read_text(encoding="utf-8").strip()
            if goal_path.is_file()
            else f"生成可追踪的 {selected_case} 需求目录和边界/状态测试用例"
        )
        if is_api_case:
            harness = Harness(
                temporary_root,
                model_gateway=gateway,
                checkpoint_provider=_EvalCheckpointProvider(),
                allowed_source_roots=[eval_source],
            )
            prepared = harness.prepare_api_scenario(
                ApiScenarioPrepareCommand(
                    source_directory=str(eval_source.resolve()),
                    workspace_id=f"live-eval-{selected_case}",
                    goal=goal,
                    environment="recorded-test",
                )
            )
            snapshot = harness.get_run(
                RunRef(workspace_id=prepared.workspace_id, run_id=prepared.run_id)
            )
            workspace = Path(temporary) / "workspaces" / prepared.workspace_id
        else:
            harness = Harness(
                Path(temporary),
                model_gateway=gateway,
                checkpoint_provider=_EvalCheckpointProvider(),
            )
            workspace = harness.create_workspace(
                CreateWorkspaceCommand(workspace_id=f"live-eval-{selected_case}")
            )
            for source in sorted(case_root.glob("source.*")):
                suffix = source.name.removeprefix("source")
                copyfile(source, workspace / "sources" / f"{selected_case}{suffix}")
            snapshot = harness.start_run(
                StartRunCommand(
                    workspace_id=f"live-eval-{selected_case}",
                    goal=goal,
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
        if is_api_case and "api_test_draft" in raw_artifacts:
            golden = evaluate_api_candidate_artifact(
                case_root,
                api_cases_content=raw_artifacts["api_test_draft"],
            )
        elif {"requirement_analysis", "testcases"}.issubset(raw_artifacts):
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
            "case": selected_case,
            "passed": structurally_complete and golden is not None and golden["passed"],
            "status": snapshot.status,
            "candidate_count": len(snapshot.candidates),
            "errors": snapshot.errors,
            "model_usage": snapshot.model_usage,
            "golden": golden,
            "generation_mode": "api_fast" if is_api_case else "standard",
        }
        if output_root:
            _export_live_eval_artifacts(
                repo_root=Path(temporary),
                workspace=workspace,
                snapshot=snapshot,
                output_root=output_root,
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
            raw_source = repo_root / raw_version.path
            copyfile(raw_source, artifact_root / raw_source.name)
        for source_path, output_name in (
            (candidate.quality_report_path, "quality-report.json"),
            (candidate.generation_report_path, "generation-report.json"),
        ):
            if source_path:
                copyfile(repo_root / source_path, artifact_root / output_name)
