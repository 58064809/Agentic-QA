from __future__ import annotations

import difflib
import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from jsonschema import ValidationError, validate

from harness.domain.budget import Budget
from harness.domain.models import ExecutionProfile
from harness.domain.schemas.api_test_cases import ApiTestCasesDraft
from harness.domain.schemas.execution_evidence import ExecutionEvidence
from harness.domain.schemas.failure_triage import FailureTriage
from harness.domain.security import sanitize_untrusted
from harness.infrastructure.manifests.registry import AgentRegistry, ToolRegistry
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.rag.provider import RagProviderConfig, RagRetriever
from harness.infrastructure.tools.api_execution import execute_api_cases
from harness.infrastructure.tools.postgres_query import (
    PostgresSourceConfig,
    execute_read_only_query,
)

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


class ToolRuntime:
    """Typed, allowlisted dispatcher with run-level idempotency and evidence records."""

    def __init__(
        self,
        *,
        store: FilesystemStore,
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
        self._builtin_handlers: dict[
            str, Callable[[str, str, dict[str, Any], ExecutionProfile], Any]
        ] = {
            "workspace.read": lambda workspace, _run, arguments, _profile: self._workspace_read(
                workspace, arguments
            ),
            "rag.retrieve": lambda workspace, _run, arguments, _profile: self._rag_retrieve(
                workspace, arguments
            ),
            "openapi.inspect": lambda workspace, _run, arguments, _profile: (
                self._openapi_inspect(workspace, arguments)
            ),
            "api.execute": self._api_execute,
            "postgres.query": lambda workspace, _run, arguments, profile: (
                self._postgres_query(workspace, arguments, profile)
            ),
            "evidence.read": lambda workspace, _run, arguments, _profile: (
                self._evidence_read(workspace, arguments)
            ),
            "artifact.diff": lambda workspace, _run, arguments, _profile: (
                self._artifact_diff(workspace, arguments)
            ),
        }

    def model_tools(self, names: list[str]) -> list[dict[str, Any]]:
        visible: list[dict[str, Any]] = []
        for name in names:
            manifest = self.tools.get(name)
            if manifest.provider != "mcp":
                visible.append(manifest.model_dump(mode="json"))
                continue
            handler = self.handlers.get(name)
            owner = getattr(handler, "__self__", None)
            snapshot = getattr(owner, "snapshot", None)
            if snapshot is None:
                continue
            variants = [
                {
                    "type": "object",
                    "required": ["tool", "arguments"],
                    "properties": {
                        "tool": {"const": tool.name},
                        "arguments": tool.input_schema or {"type": "object"},
                    },
                    "additionalProperties": False,
                }
                for tool in snapshot.tools
            ]
            if not variants:
                continue
            projected = manifest.model_copy(
                update={
                    "description": (
                        f"{manifest.description}；本 run 可用子工具："
                        + ", ".join(tool.name for tool in snapshot.tools)
                    ),
                    "input_schema": {"oneOf": variants},
                }
            )
            visible.append(projected.model_dump(mode="json"))
        return visible

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
        if manifest.idempotency in {"read", "keyed"} and idempotency_key and record.is_file():
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
                "schema_version": "agentic-qa.harness.tool-call.v2",
                "tool": tool,
                "agent": agent,
                "idempotency_key": idempotency_key,
                "arguments": sanitize_untrusted(arguments, max_chars=20_000),
                "status": "completed",
                "result": safe,
            }
        except Exception as exc:
            payload = {
                "schema_version": "agentic-qa.harness.tool-call.v2",
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
        external = self.handlers.get(tool)
        if external is not None:
            return external(arguments)
        builtin = self._builtin_handlers.get(tool)
        if builtin is None:
            raise NotImplementedError(f"tool handler is not configured: {tool}")
        return builtin(workspace, run_id, arguments, profile)

    def _postgres_query(
        self,
        workspace: str,
        arguments: dict[str, Any],
        profile: ExecutionProfile,
    ) -> dict[str, Any]:
        if profile.environment == "analysis-only":
            raise PermissionError("PostgreSQL access requires an explicit test environment")
        payload = self.store.workspace_config(workspace)
        data_sources = payload.get("data_sources") or {}
        if not isinstance(data_sources, dict):
            raise ValueError("workspace.yml data_sources must be an object")
        raw_config = data_sources.get("postgres")
        if raw_config is None:
            raise PermissionError("PostgreSQL is not configured in workspace.yml")
        config = PostgresSourceConfig.model_validate(raw_config)
        return execute_read_only_query(
            config,
            str(arguments.get("query") or ""),
            list(arguments.get("parameters") or []),
        )

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
        raw_config = self.store.workspace_config(workspace).get("rag")
        config = RagProviderConfig.from_workspace(raw_config)
        max_chunks = min(max(int(arguments.get("max_chunks") or 8), 1), 20)
        return RagRetriever(self.store, config).retrieve(
            workspace,
            str(arguments.get("query") or ""),
            max_chunks,
        )

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
