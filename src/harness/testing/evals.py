from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from harness.contracts import (
    ArtifactVariant,
    CreateWorkspaceCommand,
    ExecutionProfile,
    ReviewDecision,
    ReviewRunCommand,
    StartRunCommand,
)
from harness.domain.models import ARTIFACT_TYPES
from harness.harness import Harness
from harness.infrastructure.llm.gateway import CallableModelGateway
from harness.infrastructure.mcp.playwright import MCPBridge, MCPToolSnapshot
from harness.infrastructure.workflow.engine import (
    ARTIFACT_AGENT,
    AgentOutput,
    build_default_plan,
    default_recorded_artifact,
)


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
            allowed_tools = {item["name"] for item in tools}
            if use_fake_mcp and "mcp.playwright" in allowed_tools and not context["tool_results"]:
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
            return {
                "summary": "recorded expert response",
                "artifacts": {
                    artifact: default_recorded_artifact(artifact, context["goal"])
                    for artifact in outputs
                    if artifact in ARTIFACT_AGENT
                },
                "evidence": context["source_files"] or ["user_goal"],
                "pending": [],
                "tool_requests": [],
            }
        raise AssertionError(f"unexpected response model: {response_model}")

    return CallableModelGateway(respond)


def run_offline_eval() -> dict[str, Any]:
    """Deterministic no-network scenario covering all first-release artifact routes."""
    with TemporaryDirectory(prefix="agentic-qa-eval-") as temporary:
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
            tool_handlers={"mcp.playwright": bridge.tool_handler},
        )
        workspace = harness.create_workspace(
            CreateWorkspaceCommand(
                workspace_id="offline-eval",
                quality_policies=["city-opening-rewards"],
            )
        )
        (workspace / "sources/eval-scope.md").write_text(
            "# 离线评测范围\n\n本来源仅用于验证完整的候选、审核和发布链路。\n",
            encoding="utf-8",
        )
        workspace.joinpath("workspace.yml").write_text(
            """schema_version: agentic-qa.harness.workspace.v2
id: offline-eval
quality_policies: [city-opening-rewards]
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
                workspace_id="offline-eval",
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
                workspace_id="offline-eval",
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
