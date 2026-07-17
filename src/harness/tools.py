from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from jsonschema import ValidationError, validate

from harness.api_execution import execute_api_cases
from harness.budget import Budget
from harness.contracts import ExecutionProfile
from harness.registry import AgentRegistry, ToolRegistry
from harness.schemas.api_test_cases import ApiTestCasesDraft
from harness.schemas.execution_evidence import ExecutionEvidence
from harness.schemas.failure_triage import FailureTriage
from harness.security import sanitize_untrusted
from harness.store import WorkspaceStore

TOKEN = re.compile(r"[\w\u4e00-\u9fff-]{2,}")
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


class ToolRuntime:
    """Typed, allowlisted dispatcher with run-level idempotency and evidence records."""

    def __init__(
        self,
        *,
        store: WorkspaceStore,
        agents: AgentRegistry,
        tools: ToolRegistry,
        budget: Budget,
        handlers: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
        on_call: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.store = store
        self.agents = agents
        self.tools = tools
        self.budget = budget
        self.handlers = handlers or {}
        self.on_call = on_call

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
        if tool == "mcp.playwright" and not profile.allow_ui_mutations:
            raise PermissionError("Playwright mutations require allow_ui_mutations=true")
        try:
            validate(arguments, manifest.input_schema or {"type": "object"})
        except ValidationError as exc:
            raise ValueError(f"invalid arguments for {tool}: {exc.message}") from exc
        record_name = f"{_safe_record_name(tool, idempotency_key or arguments)}.json"
        record = (
            self.store.require_workspace(workspace) / "runs" / run_id / "tool-calls" / record_name
        )
        if manifest.idempotency == "keyed" and record.is_file():
            return json.loads(record.read_text(encoding="utf-8"))["result"]
        self.budget.consume_tool()
        try:
            result = self._dispatch(
                workspace=workspace,
                run_id=run_id,
                tool=tool,
                arguments=arguments,
                profile=profile,
            )
            safe = sanitize_untrusted(result)
            validate(safe, manifest.output_schema or {})
            payload = {
                "schema_version": "agentic-qa.harness.tool-call.v1",
                "tool": tool,
                "agent": agent,
                "idempotency_key": idempotency_key,
                "arguments": sanitize_untrusted(arguments, max_chars=20_000),
                "status": "completed",
                "result": safe,
            }
        except Exception as exc:
            payload = {
                "schema_version": "agentic-qa.harness.tool-call.v1",
                "tool": tool,
                "agent": agent,
                "idempotency_key": idempotency_key,
                "arguments": sanitize_untrusted(arguments, max_chars=20_000),
                "status": "error",
                "error": f"{type(exc).__name__}: {str(exc)[:500]}",
            }
            self.store.write_tool_record(workspace, run_id, record_name, payload)
            if self.on_call:
                self.on_call(payload)
            raise
        self.store.write_tool_record(workspace, run_id, record_name, payload)
        if self.on_call:
            self.on_call(payload)
        return safe

    def _dispatch(
        self,
        *,
        workspace: str,
        run_id: str,
        tool: str,
        arguments: dict[str, Any],
        profile: ExecutionProfile,
    ) -> Any:
        if tool in self.handlers:
            return self.handlers[tool](arguments)
        if tool == "workspace.read":
            return self._workspace_read(workspace, arguments)
        if tool == "rag.retrieve":
            return self._rag_retrieve(workspace, arguments)
        if tool == "openapi.inspect":
            return self._openapi_inspect(workspace, arguments)
        if tool == "api.execute":
            return self._api_execute(workspace, run_id, arguments, profile)
        if tool == "evidence.read":
            return self._evidence_read(workspace, arguments)
        if tool == "artifact.diff":
            return self._artifact_diff(workspace, arguments)
        raise NotImplementedError(f"tool handler is not configured: {tool}")

    def _safe_path(self, workspace: str, relative_value: Any) -> tuple[Path, Path]:
        root = self.store.require_workspace(workspace).resolve()
        relative = Path(str(relative_value or ""))
        raw = root / relative
        cursor = root
        contains_symlink = False
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink():
                contains_symlink = True
                break
        target = raw.resolve()
        if root not in target.parents or contains_symlink:
            raise ValueError("tool path is outside the workspace")
        return root, target

    def _workspace_read(self, workspace: str, arguments: dict[str, Any]) -> dict[str, Any]:
        _, target = self._safe_path(workspace, arguments.get("path"))
        if not target.is_file():
            raise ValueError("workspace.read path is not a file")
        return {
            "path": target.relative_to(self.store.require_workspace(workspace)).as_posix(),
            "content": target.read_text(encoding="utf-8")[:100_000],
        }

    def _rag_retrieve(self, workspace: str, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("rag.retrieve requires query")
        terms: set[str] = set()
        for token in TOKEN.findall(query):
            lowered = token.lower()
            terms.add(lowered)
            if any("\u4e00" <= char <= "\u9fff" for char in lowered):
                terms.update(lowered[index : index + 2] for index in range(len(lowered) - 1))
        max_chunks = min(max(int(arguments.get("max_chunks") or 8), 1), 20)
        scored: list[tuple[int, str, int, str]] = []
        for source, content in self.store.source_texts(workspace):
            for index, start in enumerate(range(0, len(content), 1200)):
                chunk = content[start : start + 1600]
                haystack = chunk.lower()
                score = sum(term in haystack for term in terms)
                if score:
                    scored.append((score, source, index, chunk))
        selected = sorted(scored, key=lambda item: (-item[0], item[1], item[2]))[:max_chunks]
        return {
            "query": query,
            "chunks": [
                {
                    "source": source,
                    "chunk_id": f"{source}#chunk-{index}",
                    "selection_reason": f"lexical_match:{score}",
                    "content": chunk,
                }
                for score, source, index, chunk in selected
            ],
        }

    def _openapi_inspect(self, workspace: str, arguments: dict[str, Any]) -> dict[str, Any]:
        root, target = self._safe_path(workspace, arguments.get("path"))
        if not target.is_file():
            raise ValueError("OpenAPI source does not exist")
        text = target.read_text(encoding="utf-8")
        try:
            payload = json.loads(text) if target.suffix.lower() == ".json" else yaml.safe_load(text)
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            raise ValueError("source is not a complete OpenAPI/Swagger document") from exc
        if not isinstance(payload, dict) or not (payload.get("openapi") or payload.get("swagger")):
            raise ValueError("source is not a complete OpenAPI/Swagger document")
        paths = payload.get("paths")
        if not isinstance(paths, dict) or not paths:
            raise ValueError("OpenAPI document has no paths")
        endpoints = []
        for path, item in sorted(paths.items()):
            if not isinstance(item, dict):
                continue
            for method, operation in item.items():
                if method.lower() in HTTP_METHODS and isinstance(operation, dict):
                    endpoints.append(
                        {
                            "method": method.upper(),
                            "path": str(path),
                            "operation_id": str(operation.get("operationId") or ""),
                            "summary": str(operation.get("summary") or ""),
                        }
                    )
        if not endpoints:
            raise ValueError("OpenAPI document has no HTTP operations")
        return {
            "source": target.relative_to(root).as_posix(),
            "contract_status": "confirmed",
            "endpoint_count": len(endpoints),
            "endpoints": endpoints[:500],
        }

    def _api_execute(
        self,
        workspace: str,
        run_id: str,
        arguments: dict[str, Any],
        profile: ExecutionProfile,
    ) -> dict[str, Any]:
        root, target = self._safe_path(workspace, arguments.get("cases_path"))
        if not target.is_file() or root / "published" not in target.parents:
            raise ValueError("api.execute only accepts published API cases")
        payload = yaml.safe_load(target.read_text(encoding="utf-8"))
        cases = ApiTestCasesDraft.model_validate(payload)
        evidence = execute_api_cases(
            cases.cases,
            run_id=run_id,
            source_cases_path=target.relative_to(root).as_posix(),
            profile=profile,
            env=os.environ,
        )
        return evidence.model_dump(mode="json")

    def _evidence_read(self, workspace: str, arguments: dict[str, Any]) -> dict[str, Any]:
        _, target = self._safe_path(workspace, arguments.get("path"))
        if not target.is_file():
            raise ValueError("evidence path does not exist")
        payload = json.loads(target.read_text(encoding="utf-8"))
        schema = payload.get("schema_version") if isinstance(payload, dict) else None
        if schema == "agentic-qa.execution-evidence.v1":
            return ExecutionEvidence.model_validate(payload).model_dump(mode="json")
        if schema == "agentic-qa.failure-triage.v1":
            return FailureTriage.model_validate(payload).model_dump(mode="json")
        raise ValueError(f"unsupported evidence schema: {schema}")

    def _artifact_diff(self, workspace: str, arguments: dict[str, Any]) -> dict[str, Any]:
        _, before = self._safe_path(workspace, arguments.get("before"))
        _, after = self._safe_path(workspace, arguments.get("after"))
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
