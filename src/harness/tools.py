from __future__ import annotations

import difflib
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from harness.budget import Budget
from harness.contracts import ExecutionProfile
from harness.registry import AgentRegistry, ToolRegistry
from harness.security import sanitize_untrusted
from harness.store import WorkspaceStore


class ToolRuntime:
    """Typed, allowlisted tool dispatcher with run-level idempotency records."""

    def __init__(
        self,
        *,
        store: WorkspaceStore,
        agents: AgentRegistry,
        tools: ToolRegistry,
        budget: Budget,
        handlers: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
    ) -> None:
        self.store = store
        self.agents = agents
        self.tools = tools
        self.budget = budget
        self.handlers = handlers or {}

    def call(
        self,
        *,
        workspace: str,
        run_id: str,
        agent: str,
        tool: str,
        arguments: dict[str, Any],
        profile: ExecutionProfile,
        idempotency_key: str | None = None,
    ) -> Any:
        manifest = self.tools.get(tool)
        if tool not in self.agents.get(agent).tool_allowlist:
            raise PermissionError(f"{agent} is not allowed to use {tool}")
        if manifest.idempotency == "keyed" and not idempotency_key:
            raise ValueError(f"{tool} requires an idempotency key")
        if manifest.risk.value == "test_mutation" and profile.environment == "analysis-only":
            raise PermissionError("state-changing test tools require an explicit test environment")
        record = (
            self.store.require_workspace(workspace)
            / "runs"
            / run_id
            / "tool-calls"
            / f"{_safe_record_name(tool, idempotency_key or arguments)}.json"
        )
        if manifest.idempotency == "keyed" and record.is_file():
            return json.loads(record.read_text(encoding="utf-8"))["result"]
        self.budget.consume_tool()

        if tool == "workspace.read":
            result = self._workspace_read(workspace, arguments)
        elif tool == "artifact.diff":
            result = self._artifact_diff(workspace, arguments)
        elif tool in self.handlers:
            result = self.handlers[tool](arguments)
        else:
            raise NotImplementedError(f"tool handler is not configured: {tool}")
        safe = sanitize_untrusted(result)
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(
            json.dumps(
                {
                    "schema_version": "agentic-qa.harness.tool-call.v1",
                    "tool": tool,
                    "idempotency_key": idempotency_key,
                    "result": safe,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return safe

    def _workspace_read(self, workspace: str, arguments: dict[str, Any]) -> dict[str, Any]:
        root = self.store.require_workspace(workspace)
        relative = Path(str(arguments.get("path") or ""))
        target = (root / relative).resolve()
        if root.resolve() not in target.parents or target.is_symlink() or not target.is_file():
            raise ValueError("workspace.read path is outside the workspace or is not a file")
        return {
            "path": relative.as_posix(),
            "content": target.read_text(encoding="utf-8")[:100_000],
        }

    def _artifact_diff(self, workspace: str, arguments: dict[str, Any]) -> dict[str, Any]:
        root = self.store.require_workspace(workspace)
        before = (root / str(arguments.get("before") or "")).resolve()
        after = (root / str(arguments.get("after") or "")).resolve()
        if root.resolve() not in before.parents or root.resolve() not in after.parents:
            raise ValueError("artifact.diff path escaped workspace")
        lines = difflib.unified_diff(
            before.read_text(encoding="utf-8").splitlines(),
            after.read_text(encoding="utf-8").splitlines(),
            fromfile=before.name,
            tofile=after.name,
            lineterm="",
        )
        return {"diff": "\n".join(lines)[:100_000]}


def _safe_record_name(tool: str, value: Any) -> str:
    digest = hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()[:20]
    return f"{tool.replace('.', '-')}-{digest}"
