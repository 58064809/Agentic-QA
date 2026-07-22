from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from queue import Queue
from threading import Thread

from harness.domain.models import HarnessEvent, ReviewDecision, RunSnapshot, StartRunCommand
from harness.infrastructure.mcp.playwright import (
    MCPToolSnapshot,
    PlaywrightMCPConfig,
    SynchronousOfficialMCPClient,
)
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.workflow.engine import HarnessEngine


class LangGraphWorkflowRunner:
    def __init__(self, *, store: FilesystemStore, engine: HarnessEngine) -> None:
        self._store = store
        self._engine = engine

    def start(self, command: StartRunCommand) -> RunSnapshot:
        with self._configured_tool_handlers(command.workspace_id) as handlers:
            return self._engine.execute(command, tool_handlers=handlers)

    def stream(self, command: StartRunCommand) -> Iterator[HarnessEvent]:
        queue: Queue[HarnessEvent | BaseException | None] = Queue()

        def worker() -> None:
            try:
                with self._configured_tool_handlers(command.workspace_id) as handlers:
                    self._engine.execute(command, emit=queue.put, tool_handlers=handlers)
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

    def resume(self, snapshot: RunSnapshot) -> RunSnapshot:
        with self._configured_tool_handlers(
            snapshot.workspace_id, run_id=snapshot.run_id
        ) as handlers:
            return self._engine.resume(snapshot, tool_handlers=handlers)

    def review(self, snapshot: RunSnapshot, decision: ReviewDecision) -> RunSnapshot:
        return self._engine.resume(snapshot, decision)

    @contextmanager
    def _configured_tool_handlers(
        self,
        workspace_id: str,
        *,
        run_id: str | None = None,
    ) -> Iterator[dict[str, object]]:
        payload = self._store.workspace_config(workspace_id)
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
            if client.snapshot is None or not client.snapshot.tools:
                raise RuntimeError("Playwright MCP did not return allowlisted tools")
            if run_id is not None:
                self._validate_frozen_mcp_snapshot(workspace_id, run_id, client.snapshot)
            handlers = dict(self._engine.tool_handlers)
            handlers["mcp.playwright"] = client.tool_handler
            yield handlers

    def _validate_frozen_mcp_snapshot(
        self,
        workspace_id: str,
        run_id: str,
        live_snapshot: MCPToolSnapshot,
    ) -> None:
        record = (
            self._store.require_workspace(workspace_id)
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
