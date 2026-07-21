from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from queue import Queue
from threading import Thread

from harness.budget import BudgetLimits
from harness.contracts import HarnessEvent, ReviewDecision, RunSnapshot, TaskRequest
from harness.engine import HarnessEngine
from harness.mcp import MCPToolSnapshot, PlaywrightMCPConfig, SynchronousOfficialMCPClient
from harness.model import ModelGateway, model_gateway_from_env
from harness.registry import AgentRegistry, SkillRegistry, ToolRegistry
from harness.store import WorkspaceStore


class Harness:
    """Stable Python facade. LangGraph and other orchestration backends remain internal."""

    def __init__(
        self,
        repo_root: Path | str = ".",
        *,
        model_gateway: ModelGateway | None = None,
        budget_limits: BudgetLimits | None = None,
        agent_registry: AgentRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_handlers: dict[str, object] | None = None,
    ) -> None:
        self.store = WorkspaceStore(repo_root)
        self.tools = tool_registry or ToolRegistry.builtin()
        self.skills = skill_registry or SkillRegistry.builtin()
        self.agents = agent_registry or AgentRegistry.builtin(
            skills=self.skills,
            tools=self.tools,
        )
        self._engine = HarnessEngine(
            store=self.store,
            agents=self.agents,
            skills=self.skills,
            tools=self.tools,
            model=model_gateway or model_gateway_from_env(),
            limits=budget_limits,
            tool_handlers=tool_handlers,
        )

    def run(self, request: TaskRequest) -> RunSnapshot:
        with self._configured_tool_handlers(request.workspace) as handlers:
            return self._engine.execute(request, tool_handlers=handlers)

    def stream(self, request: TaskRequest) -> Iterator[HarnessEvent]:
        queue: Queue[HarnessEvent | BaseException | None] = Queue()

        def worker() -> None:
            try:
                with self._configured_tool_handlers(request.workspace) as handlers:
                    self._engine.execute(request, emit=queue.put, tool_handlers=handlers)
            except BaseException as exc:
                queue.put(exc)
            finally:
                queue.put(None)

        thread = Thread(target=worker, name="agentic-qa-harness", daemon=True)
        thread.start()
        while True:
            item = queue.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            yield item
        thread.join()

    def resume(
        self,
        run_id: str,
        decision: ReviewDecision | None = None,
    ) -> RunSnapshot:
        snapshot = self.store.load_snapshot(run_id)
        if snapshot.status in {"partial", "needs_human_review"}:
            return self._engine.resume(snapshot, decision)
        with self._configured_tool_handlers(
            snapshot.workspace,
            run_id=snapshot.run_id,
        ) as handlers:
            return self._engine.resume(snapshot, decision, tool_handlers=handlers)

    def inspect(self, run_id: str) -> RunSnapshot:
        return self.store.load_snapshot(run_id)

    def init_workspace(self, workspace: str) -> Path:
        request = TaskRequest(workspace=workspace, goal="workspace validation")
        return self.store.init_workspace(request.workspace)

    @contextmanager
    def _configured_tool_handlers(
        self,
        workspace: str,
        *,
        run_id: str | None = None,
    ) -> Iterator[dict[str, object]]:
        payload = self.store.workspace_config(workspace)
        mcp = payload.get("mcp") or {}
        if not isinstance(mcp, dict):
            raise ValueError("workspace.yml mcp must be an object")
        unknown_servers = sorted(set(mcp) - {"playwright"})
        if unknown_servers:
            raise ValueError(f"unsupported workspace MCP servers: {', '.join(unknown_servers)}")
        raw_playwright = mcp.get("playwright")
        if raw_playwright is None:
            yield dict(self._engine.tool_handlers)
            return
        if "mcp.playwright" in self._engine.tool_handlers:
            raise ValueError(
                "Playwright MCP cannot be configured in workspace.yml and injected in code"
            )
        config = PlaywrightMCPConfig.model_validate(raw_playwright)
        with SynchronousOfficialMCPClient(config) as client:
            if client.snapshot is None:
                raise RuntimeError("Playwright MCP did not return a tool snapshot")
            if not client.snapshot.tools:
                raise RuntimeError("Playwright MCP advertised none of the allowlisted tools")
            if run_id is not None:
                self._validate_frozen_mcp_snapshot(workspace, run_id, client.snapshot)
            handlers = dict(self._engine.tool_handlers)
            handlers["mcp.playwright"] = client.tool_handler
            yield handlers

    def _validate_frozen_mcp_snapshot(
        self,
        workspace: str,
        run_id: str,
        live_snapshot: MCPToolSnapshot,
    ) -> None:
        record = (
            self.store.require_workspace(workspace)
            / "runs"
            / run_id
            / "tool-calls"
            / "mcp-playwright-snapshot.json"
        )
        if not record.is_file():
            raise RuntimeError("run is missing its frozen Playwright MCP tool snapshot")
        payload = json.loads(record.read_text(encoding="utf-8"))
        frozen = MCPToolSnapshot.model_validate(payload.get("snapshot"))
        if frozen != live_snapshot:
            raise RuntimeError("Playwright MCP tools changed since this run was frozen")
