from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from harness import (
    ArtifactDiffEndpoint,
    ArtifactVariant,
    CreateWorkspaceCommand,
    ExecutionProfile,
    GetArtifactDiffQuery,
    Harness,
    ResumeRunCommand,
    ReviewDecision,
    ReviewRunCommand,
    RunRef,
    StartRunCommand,
)
from harness.application.qa_design import parse_testcase_markdown
from harness.domain.schemas.qa_design import CoverageMapping
from harness.domain.schemas.qa_design import TestCaseSet as QATestCaseSet
from harness.infrastructure.llm.gateway import CallableModelGateway
from harness.infrastructure.mcp.playwright import MCPBridge, MCPToolSnapshot
from harness.infrastructure.workflow.engine import (
    _targeted_testcase_patch_context,
    default_recorded_testcase_set,
)
from harness.testing.evals import recorded_model_gateway


def _prompt_context(prompt: str, response_model: type) -> dict[str, Any]:
    if response_model.__name__ != "AgentOutput":
        return {}
    envelope = json.loads(prompt)
    return {
        **envelope.get("trusted_context", {}),
        **envelope.get("untrusted_context", {}),
    }


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


def test_api_test_draft_is_typed_yaml_and_keeps_human_review_gate(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    workspace = _create(harness)

    snapshot = harness.start_run(
        StartRunCommand(
            workspace_id="demo",
            goal="为福利活动设计 API 测试",
            expected_artifacts=["api_test_draft"],
        )
    )

    assert snapshot.status == "needs_human_review"
    candidate = snapshot.candidates[0]
    assert candidate.path.endswith("/api_test_draft/raw.yml")
    candidate_root = (tmp_path / candidate.path).parent
    manifest = json.loads((candidate_root / "manifest.json").read_text(encoding="utf-8"))
    payload = yaml.safe_load((candidate_root / "raw.yml").read_text(encoding="utf-8"))
    assert manifest["media_type"] == "application/yaml"
    assert payload["schema_version"] == "agentic-qa.api-cases.v1.1"
    assert payload["cases"][0]["contract_status"] == "missing"
    assert payload["cases"][0]["request"]["method"] is None
    assert payload["cases"][0]["request"]["path"] is None
    assert not (workspace / "published/api_test_draft/current.yml").exists()

    published = harness.review_run(
        ReviewRunCommand(
            workspace_id="demo",
            run_id=snapshot.run_id,
            decision=ReviewDecision(
                intent="approve",
                target_artifact="api_test_draft",
                reason="人工确认待契约项表达准确",
                reviewed_by="qa_owner",
                versions=[candidate.version_ref(ArtifactVariant.RAW)],
            ),
        )
    )

    assert published.status == "published"
    assert (workspace / "published/api_test_draft/current.yml").is_file()


def test_api_discovery_report_is_sanitized_and_stops_at_review_gate(tmp_path: Path) -> None:
    recorded = recorded_model_gateway()
    discovery_tools: list[set[str]] = []

    class RecordingGateway:
        def __getattr__(self, name: str) -> Any:
            return getattr(recorded, name)

        def structured(self, **kwargs: Any) -> Any:
            prompt = json.loads(kwargs["prompt"])
            task = prompt.get("trusted_context", {}).get("task", {})
            if task.get("expected_outputs") == ["api_discovery_report"]:
                discovery_tools.append({str(tool["name"]) for tool in kwargs.get("tools") or []})
            return recorded.structured(**kwargs)

    harness = Harness(tmp_path, model_gateway=RecordingGateway())
    workspace = _create(harness)
    (workspace / "sources/network-capture.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "method": "POST",
                        "url": "https://example.test/api/assist?token=secret-value",
                        "status": 200,
                        "resource_type": "xhr",
                        "request_headers": {
                            "Authorization": "Bearer secret-value",
                        },
                        "request_body": {
                            "user_id": "user-1",
                            "token": "secret-value",
                            "```break": "untrusted-markdown",
                        },
                        "response_body": {"accepted": True},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    snapshot = harness.start_run(
        StartRunCommand(
            workspace_id="demo",
            goal="基于冻结抓包生成接口发现报告",
            expected_artifacts=["api_discovery_report"],
        )
    )

    assert snapshot.status == "needs_human_review"
    candidate = snapshot.candidates[0]
    report = (tmp_path / candidate.path).read_text(encoding="utf-8")
    assert candidate.partial is False
    assert "## 接口调用链" in report
    assert "POST" in report and "/api/assist" in report
    assert "不代表完整 API 契约" in report
    assert "secret-value" not in report
    assert "```json" not in report
    assert len(candidate.attachments) == 1
    attachment = candidate.attachments[0]
    assert attachment.name == "discovery-catalog.json"
    catalog_text = (tmp_path / attachment.path).read_text(encoding="utf-8")
    catalog_export = json.loads(catalog_text)
    assert catalog_export["schema_version"] == "agentic-qa.api-discovery-export.v1"
    assert catalog_export["run_id"] == snapshot.run_id
    assert catalog_export["catalogs"][0]["candidates"][0]["path"] == "/api/assist"
    assert "secret-value" not in catalog_text
    candidate_files = {path.name for path in (tmp_path / candidate.path).parent.iterdir()}
    assert "discovery-catalog.json" in candidate_files
    assert not any(path.endswith(".har") for path in candidate_files)
    assert discovery_tools
    assert all(tools == {"network.capture.inspect"} for tools in discovery_tools)
    assert not (workspace / "published/api_discovery_report/current.md").exists()

    approved_ref = candidate.version_ref(ArtifactVariant.RAW)
    assert approved_ref.attachments[0].content_sha256 == attachment.content_sha256

    published = harness.review_run(
        ReviewRunCommand(
            workspace_id="demo",
            run_id=snapshot.run_id,
            decision=ReviewDecision(
                intent="approve",
                target_artifact="api_discovery_report",
                reason="人工确认观察证据与脱敏说明",
                reviewed_by="qa_owner",
                versions=[candidate.version_ref(ArtifactVariant.RAW)],
            ),
        )
    )

    assert published.status == "published"
    assert (workspace / "published/api_discovery_report/current.md").is_file()
    published_catalog = workspace / "published/api_discovery_report/current.catalog.json"
    assert published_catalog.read_text(encoding="utf-8") == catalog_text
    history_catalog = (
        workspace / "published/api_discovery_report/history" / f"{snapshot.run_id}.catalog.json"
    )
    assert history_catalog.read_text(encoding="utf-8") == catalog_text


def test_live_api_discovery_uses_playwright_facade_and_stops_at_review_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTIC_QA_BASE_URL", "https://qa.example.test")
    subtool_calls: list[str] = []

    def caller(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        subtool_calls.append(name)
        if name == "browser_network_requests":
            text = (
                "### Result\n"
                "1. [GET] https://qa.example.test/ => [200]\n"
                "2. [POST] https://qa.example.test/api/activities/123/assist"
                "?token=live-secret => [200]"
            )
        elif name == "browser_network_request" and arguments.get("index") == 1:
            text = (
                "### Result\n#1 [GET] https://qa.example.test/\n\n"
                "  General\n"
                "    status: [200]\n"
                "    duration: 10ms\n"
                "    type: document\n"
            )
        elif name == "browser_network_request" and arguments.get("part") == "request-body":
            text = '### Result\n{"phone":"13800138000","token":"live-secret"}'
        elif name == "browser_network_request" and arguments.get("part") == "response-body":
            text = '### Result\n{"accepted":true,"access_token":"response-secret"}'
        elif name == "browser_network_request":
            text = (
                "### Result\n"
                "#2 [POST] https://qa.example.test/api/activities/123/assist"
                "?token=live-secret\n\n"
                "  General\n"
                "    status: [200]\n"
                "    duration: 30ms\n"
                "    type: xhr\n"
                "    mimeType: application/json\n\n"
                "  Request headers\n"
                "    authorization: Bearer live-secret\n"
                "    content-type: application/json\n\n"
                "  Response headers\n"
                "    content-type: application/json\n"
            )
        else:
            text = "### Result\nnavigated\n### Page\n- Page URL: https://qa.example.test/\n"
        return {"content": [{"type": "text", "text": text}], "isError": False}

    listed_tools = [
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
        caller,
    )
    harness = Harness(
        tmp_path,
        model_gateway=recorded_model_gateway(),
        tool_handlers={"mcp.playwright": bridge.tool_handler},
    )
    workspace = _create(harness)
    config = yaml.safe_load((workspace / "workspace.yml").read_text(encoding="utf-8"))
    config["execution"]["environments"]["qa"] = {
        "base_url_env": "AGENTIC_QA_BASE_URL",
        "allowed_http_methods": ["GET", "HEAD", "OPTIONS", "POST"],
        "allow_ui_mutations": True,
        "max_request_timeout_seconds": 10,
    }
    (workspace / "workspace.yml").write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    snapshot = harness.start_run(
        StartRunCommand(
            workspace_id="demo",
            goal="打开测试站点并生成实时接口发现报告",
            expected_artifacts=["api_discovery_report"],
            execution_profile=ExecutionProfile(
                environment="qa",
                base_url_env="AGENTIC_QA_BASE_URL",
                allowed_http_methods=["GET", "HEAD", "OPTIONS", "POST"],
                allow_ui_mutations=True,
                request_timeout_seconds=10,
            ),
        )
    )

    assert snapshot.status == "needs_human_review"
    recorded_tools = [call["tool"] for call in snapshot.tool_calls]
    assert recorded_tools.count("mcp.playwright") == 2  # frozen snapshot + navigation
    assert recorded_tools.count("network.capture.live") == 1
    assert subtool_calls.count("browser_navigate") == 1
    assert subtool_calls.count("browser_network_requests") == 1
    candidate = snapshot.candidates[0]
    report = (tmp_path / candidate.path).read_text(encoding="utf-8")
    assert "playwright_mcp" in report
    assert "https://qa.example.test" in report
    assert "/api/activities/{id}/assist" in report
    assert "live-secret" not in report
    assert "response-secret" not in report
    assert "13800138000" not in report
    live_catalog = (tmp_path / candidate.attachments[0].path).read_text(encoding="utf-8")
    assert "playwright_mcp" in live_catalog
    assert "live-secret" not in live_catalog
    assert "response-secret" not in live_catalog
    assert "13800138000" not in live_catalog
    assert not (workspace / "published/api_discovery_report/current.md").exists()


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


def test_invalid_model_plans_fall_back_to_deterministic_artifact_topology(
    tmp_path: Path,
) -> None:
    recorded = recorded_model_gateway()
    planner_calls = 0

    def respond(
        *,
        prompt: str,
        response_model: type,
        **kwargs: Any,
    ) -> Any:
        nonlocal planner_calls
        if response_model.__name__ == "QAPlan":
            planner_calls += 1
            return {
                "tasks": [
                    {
                        "id": "incomplete-requirement-analysis",
                        "objective": "analyze requirements without internal typed context",
                        "agent": "requirement_analyst",
                        "expected_outputs": ["requirement_analysis"],
                        "evidence_requirements": [
                            {"kind": "source", "description": "frozen requirement source"}
                        ],
                    },
                    {
                        "id": "invalid-test-design",
                        "objective": "generate tests without typed dependencies",
                        "agent": "test_designer",
                        "expected_outputs": ["testcases"],
                        "evidence_requirements": [
                            {"kind": "trace", "description": "requirement trace"}
                        ],
                    },
                ]
            }
        return recorded._callback(  # noqa: SLF001 - recorded gateway is a test fixture
            prompt=prompt,
            response_model=response_model,
            **kwargs,
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    workspace = _create(harness)

    snapshot = harness.start_run(
        StartRunCommand(
            workspace_id="demo",
            goal="test login",
            expected_artifacts=["requirement_analysis", "testcases"],
        )
    )

    assert snapshot.status == "needs_human_review"
    assert snapshot.errors == []
    assert planner_calls == 3
    assert {item.artifact for item in snapshot.candidates} == {
        "requirement_analysis",
        "testcases",
    }
    assert snapshot.plan is not None
    assert [task.id for task in snapshot.plan.tasks] == [
        "analyze_requirements",
        "analyze_risks",
        "produce_testcases",
    ]
    events = [
        json.loads(line)
        for line in (workspace / f"runs/{snapshot.run_id}/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    fallback = [item for item in events if item["type"] == "plan_fallback_applied"]
    assert len(fallback) == 1
    assert fallback[0]["data"]["failed_attempts"] == 3
    assert fallback[0]["data"]["fallback"] == "deterministic_artifact_topology"
    assert "requires exactly one root RequirementCatalog task" in fallback[0]["data"]["reason"]


def test_invalid_testcase_batch_schema_uses_local_repair_instead_of_replanning(
    tmp_path: Path,
) -> None:
    recorded = recorded_model_gateway()
    invalid_batches = 0
    repair_calls = 0

    def respond(
        *,
        prompt: str,
        response_model: type,
        **kwargs: Any,
    ) -> Any:
        nonlocal invalid_batches, repair_calls
        result = recorded._callback(  # noqa: SLF001 - recorded gateway is a test fixture
            prompt=prompt,
            response_model=response_model,
            **kwargs,
        )
        context = _prompt_context(prompt, response_model)
        if (
            response_model.__name__ == "AgentOutput"
            and context.get("task", {}).get("agent") == "test_designer"
            and context.get("rule_batch")
        ):
            if context.get("validation_feedback"):
                repair_calls += 1
            elif invalid_batches == 0:
                invalid_batches += 1
                result = deepcopy(result)
                testcase_set = result["testcase_set"]
                old_id = testcase_set["cases"][0]["case_id"]
                testcase_set["cases"][0]["case_id"] = "TC-invalid-a"
                testcase_set["coverage"][0]["case_ids"] = ["TC-invalid-a"]
                assert old_id != "TC-invalid-a"
        return result

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    workspace = _create(harness)

    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test login"))

    assert snapshot.status == "needs_human_review"
    assert invalid_batches == 1
    assert repair_calls == 1
    assert snapshot.plan is not None
    assert snapshot.plan.revision == 0
    events = [
        json.loads(line)
        for line in (workspace / f"runs/{snapshot.run_id}/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert not [item for item in events if item["type"] == "agent_failed"]
    repairs = [
        item
        for item in events
        if item["type"] == "model_routed" and item["data"].get("phase") == "rule_batch_repair"
    ]
    assert len(repairs) == 1
    generation_report = json.loads(
        (tmp_path / snapshot.candidates[0].generation_report_path).read_text(encoding="utf-8")
    )
    assert generation_report["model_calls"][0]["outcome"] == "invalid_structured_output"
    assert generation_report["model_calls"][1]["outcome"] == "quality_accepted"


def test_exhausted_testcase_batch_repairs_use_traceable_deterministic_fallback(
    tmp_path: Path,
) -> None:
    recorded = recorded_model_gateway()
    invalid_batch_calls = 0

    def respond(
        *,
        prompt: str,
        response_model: type,
        **kwargs: Any,
    ) -> Any:
        nonlocal invalid_batch_calls
        result = recorded._callback(  # noqa: SLF001 - recorded gateway is a test fixture
            prompt=prompt,
            response_model=response_model,
            **kwargs,
        )
        context = _prompt_context(prompt, response_model)
        if (
            response_model.__name__ == "AgentOutput"
            and context.get("task", {}).get("agent") == "test_designer"
            and context.get("rule_batch")
        ):
            invalid_batch_calls += 1
            result = deepcopy(result)
            result["testcase_set"]["cases"][0]["test_data"] = []
        return result

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    workspace = _create(harness)

    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="test login"))

    assert snapshot.status == "needs_human_review"
    assert snapshot.plan is not None
    assert snapshot.plan.revision == 0
    assert invalid_batch_calls == 3
    events = [
        json.loads(line)
        for line in (workspace / f"runs/{snapshot.run_id}/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    fallbacks = [item for item in events if item["type"] == "testcase_batch_fallback_applied"]
    assert len(fallbacks) == 1
    assert fallbacks[0]["data"]["reason"] == "structured_output_repair_exhausted"
    assert not [item for item in events if item["type"] == "agent_failed"]
    testcase_candidate = next(item for item in snapshot.candidates if item.artifact == "testcases")
    testcase_set = parse_testcase_markdown(
        (tmp_path / testcase_candidate.path).read_text(encoding="utf-8")
    )
    assert all(
        any("规则驱动基础用例" in pending for pending in case.pending_items)
        for case in testcase_set.cases
    )


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
        context = _prompt_context(prompt, response_model)
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


def test_quality_patch_context_contains_only_reviewer_blocker_cases() -> None:
    base = default_recorded_testcase_set("test login")
    first = base.cases[0]
    second = first.model_copy(
        update={
            "case_id": "TC-SECOND-002",
            "rule_ids": ["SRC-OTHER-002"],
        }
    )
    current = QATestCaseSet(
        requirement_catalog_hash=base.requirement_catalog_hash,
        cases=[first, second],
        coverage=[
            base.coverage[0],
            CoverageMapping(
                rule_id="SRC-OTHER-002",
                case_ids=[second.case_id],
                rationale="第二条独立规则的覆盖。",
            ),
        ],
    )
    feedback = [
        {
            "kind": "quality_gate",
            "error": json.dumps(
                {
                    "blockers": [
                        {
                            "case_id": first.case_id,
                            "rule_id": first.rule_ids[0],
                        }
                    ]
                }
            ),
        }
    ]

    targeted = _targeted_testcase_patch_context(current, feedback)

    assert targeted is not None
    testcase_context, rule_ids = targeted
    assert [case.case_id for case in testcase_context.cases] == [first.case_id]
    assert [mapping.rule_id for mapping in testcase_context.coverage] == first.rule_ids
    assert rule_ids == set(first.rule_ids)


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
        if call["prompt_template_version"] == "requirement-fragment-v3"
    ]
    assert len(fragment_calls) == 2
    assert {
        selection["source"] for call in fragment_calls for selection in call["source_selection"]
    } == {"sources/a.md", "sources/b.md"}
    assert all(call["raw_response_sha256"] for call in report["model_calls"])
    assert all(call["latency_ms"] >= 0 for call in report["model_calls"])
    assert all(call["finish_reason"] == "recorded" for call in report["model_calls"])
    assert all(call["input_context_characters"] > 0 for call in report["model_calls"])
    assert all(call["prompt_sha256"] for call in report["model_calls"])
    assert all(call["prompt_reference_versions"] for call in report["model_calls"])
    assert all(
        selection["raw_sha256"] for call in fragment_calls for selection in call["source_selection"]
    )


def test_single_source_requirement_catalog_is_not_regenerated(tmp_path: Path) -> None:
    recorded = recorded_model_gateway()
    requirement_calls = 0

    def respond(
        *,
        prompt: str,
        response_model: type,
        **kwargs: Any,
    ) -> Any:
        nonlocal requirement_calls
        context = _prompt_context(prompt, response_model)
        if context.get("task", {}).get("agent") == "requirement_analyst":
            requirement_calls += 1
        return recorded._callback(  # noqa: SLF001 - recorded gateway is a test fixture
            prompt=prompt,
            response_model=response_model,
            **kwargs,
        )

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    workspace = _create(harness)
    (workspace / "sources/requirements.md").write_text(
        "# 规则\n\n每位用户每天最多获得五次抽奖机会。",
        encoding="utf-8",
    )

    snapshot = harness.start_run(
        StartRunCommand(
            workspace_id="demo",
            goal="analyze lottery requirements",
            expected_artifacts=["requirement_analysis"],
        )
    )

    assert snapshot.status == "needs_human_review"
    assert requirement_calls == 1
    report = json.loads(
        (tmp_path / snapshot.candidates[0].generation_report_path).read_text(encoding="utf-8")
    )
    assert len(report["model_calls"]) == 1
    assert report["model_calls"][0]["outcome"] == "quality_accepted"


def test_typed_requirement_output_ignores_redundant_markdown_without_retry(
    tmp_path: Path,
) -> None:
    recorded = recorded_model_gateway()
    merge_calls = 0

    def respond(
        *,
        prompt: str,
        response_model: type,
        **kwargs: Any,
    ) -> Any:
        nonlocal merge_calls
        context = _prompt_context(prompt, response_model)
        payload = recorded._callback(  # noqa: SLF001 - recorded gateway is a test fixture
            prompt=prompt,
            response_model=response_model,
            **kwargs,
        )
        if context.get("task", {}).get("agent") == "requirement_analyst" and context.get(
            "source_fragments"
        ):
            merge_calls += 1
            payload["artifacts"] = {"requirement_analysis": "# redundant model markdown"}
        return payload

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    workspace = _create(harness)
    (workspace / "sources/a.md").write_text("# A\n\n规则A。", encoding="utf-8")
    (workspace / "sources/b.md").write_text("# B\n\n规则B。", encoding="utf-8")

    snapshot = harness.start_run(
        StartRunCommand(
            workspace_id="demo",
            goal="merge requirement sources",
            expected_artifacts=["requirement_analysis"],
        )
    )

    assert snapshot.status == "needs_human_review"
    assert merge_calls == 1
    events = [
        json.loads(line)
        for line in (workspace / f"runs/{snapshot.run_id}/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    ignored = [item for item in events if item["type"] == "redundant_model_artifacts_ignored"]
    assert len(ignored) == 1
    assert ignored[0]["data"]["artifacts"] == ["requirement_analysis"]


def test_typed_risk_output_ignores_redundant_markdown_without_retry(tmp_path: Path) -> None:
    recorded = recorded_model_gateway()
    risk_calls = 0

    def respond(
        *,
        prompt: str,
        response_model: type,
        **kwargs: Any,
    ) -> Any:
        nonlocal risk_calls
        context = _prompt_context(prompt, response_model)
        payload = recorded._callback(  # noqa: SLF001 - recorded gateway is a test fixture
            prompt=prompt,
            response_model=response_model,
            **kwargs,
        )
        if context.get("task", {}).get("agent") == "risk_strategist":
            risk_calls += 1
            payload["artifacts"] = {"risk_context": "# redundant model markdown"}
        return payload

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    workspace = _create(harness)
    (workspace / "sources/requirements.md").write_text(
        "# 规则\n\n每位用户每天最多获得五次抽奖机会。",
        encoding="utf-8",
    )

    snapshot = harness.start_run(StartRunCommand(workspace_id="demo", goal="design lottery tests"))

    assert snapshot.status == "needs_human_review"
    assert risk_calls == 1
    events = [
        json.loads(line)
        for line in (workspace / f"runs/{snapshot.run_id}/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    ignored = [
        item
        for item in events
        if item["type"] == "redundant_model_artifacts_ignored"
        and item["agent"] == "risk_strategist"
    ]
    assert len(ignored) == 1
    assert ignored[0]["data"]["artifacts"] == ["risk_context"]


def test_invalid_requirement_fragment_schema_uses_local_repair_without_replanning(
    tmp_path: Path,
) -> None:
    recorded = recorded_model_gateway()
    fragment_calls = 0

    def respond(
        *,
        prompt: str,
        response_model: type,
        **kwargs: Any,
    ) -> Any:
        nonlocal fragment_calls
        result = recorded._callback(  # noqa: SLF001 - recorded gateway is a test fixture
            prompt=prompt,
            response_model=response_model,
            **kwargs,
        )
        context = _prompt_context(prompt, response_model)
        if response_model.__name__ == "AgentOutput" and "source_content" in context:
            fragment_calls += 1
            if fragment_calls == 1:
                result = deepcopy(result)
                result.pop("summary")
            else:
                assert context["validation_feedback"]
        return result

    harness = Harness(tmp_path, model_gateway=CallableModelGateway(respond))
    workspace = _create(harness)
    (workspace / "sources/requirements.md").write_text("# 规则\n\n登录后可抽奖。", encoding="utf-8")

    snapshot = harness.start_run(
        StartRunCommand(
            workspace_id="demo",
            goal="analyze lottery requirements",
            expected_artifacts=["requirement_analysis"],
        )
    )

    assert snapshot.status == "needs_human_review"
    assert snapshot.plan is not None
    assert snapshot.plan.revision == 0
    assert fragment_calls == 2
    events = [
        json.loads(line)
        for line in (workspace / f"runs/{snapshot.run_id}/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert not [item for item in events if item["type"] == "agent_failed"]
    repairs = [
        item
        for item in events
        if item["type"] == "model_routed" and item["data"].get("phase") == "source_fragment_repair"
    ]
    assert len(repairs) == 1
    report = json.loads(
        (tmp_path / snapshot.candidates[0].generation_report_path).read_text(encoding="utf-8")
    )
    assert report["model_calls"][0]["outcome"] == "invalid_structured_output"
    assert report["model_calls"][1]["outcome"] == "quality_accepted"


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
        context = _prompt_context(prompt, response_model)
        payload = recorded._callback(  # noqa: SLF001 - recorded gateway is a test fixture
            prompt=prompt,
            response_model=response_model,
            **kwargs,
        )
        if context.get("rule_batch"):
            batch_rule_ids.append(context["rule_batch"]["rule_ids"])
        if context.get("task", {}).get("agent") == "requirement_analyst" and context.get(
            "source_content"
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
    assert [len(rule_ids) for rule_ids in batch_rule_ids] == [6, 1]
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
        if call["prompt_template_version"] == "testcase-rule-batch-v3"
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
        context = _prompt_context(prompt, response_model)
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
            assert "source_prefetched" not in context
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
        context = _prompt_context(prompt, response_model)
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
