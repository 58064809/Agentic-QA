from __future__ import annotations

import difflib
import hashlib
import json
import os
import unicodedata
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

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
from harness.infrastructure.tools.network_capture import inspect_network_capture
from harness.infrastructure.tools.openapi import inspect_openapi
from harness.infrastructure.tools.playwright_network import inspect_playwright_network
from harness.infrastructure.tools.postgres_query import (
    PostgresSourceConfig,
    execute_read_only_query,
)


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
            "workspace.read": lambda workspace, run, arguments, _profile: self._workspace_read(
                workspace, run, arguments
            ),
            "rag.retrieve": lambda workspace, run, arguments, _profile: self._rag_retrieve(
                workspace, run, arguments
            ),
            "openapi.inspect": lambda workspace, run, arguments, _profile: self._openapi_inspect(
                workspace, run, arguments
            ),
            "network.capture.inspect": lambda workspace, run, arguments, _profile: (
                self._network_capture_inspect(workspace, run, arguments)
            ),
            "network.capture.live": self._network_capture_live,
            "api.execute": self._api_execute,
            "postgres.query": lambda workspace, _run, arguments, profile: self._postgres_query(
                workspace, arguments, profile
            ),
            "evidence.read": lambda workspace, _run, arguments, _profile: self._evidence_read(
                workspace, arguments
            ),
            "artifact.diff": lambda workspace, _run, arguments, _profile: self._artifact_diff(
                workspace, arguments
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
            for tool in snapshot.tools:
                if tool.name in {
                    "browser_network_requests",
                    "browser_network_request",
                    "browser_run_code",
                    "browser_run_code_unsafe",
                }:
                    continue
                projected = manifest.model_copy(
                    update={
                        "name": f"{name}.{tool.name}",
                        "description": tool.description or manifest.description,
                        "input_schema": tool.input_schema or {"type": "object"},
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
        if tool == "mcp.playwright":
            self._validate_direct_playwright_call(arguments, profile)
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
            if tool == "mcp.playwright":
                self._validate_playwright_result(result, profile)
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

    def _workspace_read(
        self, workspace: str, run_id: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        requested = self._normalized_tool_path(arguments.get("path"))
        if self._is_source_path(requested):
            return self._read_frozen_source(workspace, run_id, requested)
        return self._read_workspace_runtime_file(workspace, requested)

    def _read_frozen_source(self, workspace: str, run_id: str, requested: str) -> dict[str, Any]:
        bundle = self.store.load_source_bundle(workspace, run_id)
        document = next((item for item in bundle.documents if item.path == requested), None)
        if document is None:
            raise ValueError(f"source 不属于当前 Run 的冻结 SourceBundle: {requested}")
        if document.text is None:
            raise ValueError(f"冻结 source 不可用: {document.path}")
        return {"path": document.path, "content": document.text}

    def _read_workspace_runtime_file(self, workspace: str, requested: str) -> dict[str, Any]:
        _, target = self._safe_path(workspace, requested)
        if not target.is_file():
            raise ValueError("workspace.read path is not a file")
        return {
            "path": target.relative_to(self.store.require_workspace(workspace)).as_posix(),
            "content": target.read_text(encoding="utf-8")[:100_000],
        }

    @staticmethod
    def _normalized_tool_path(value: Any) -> str:
        requested = unicodedata.normalize("NFC", str(value or "").replace("\\", "/"))
        path = PurePosixPath(requested)
        if (
            path.is_absolute()
            or not requested
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("tool path is outside the workspace")
        return path.as_posix()

    @staticmethod
    def _is_source_path(requested: str) -> bool:
        return PurePosixPath(requested).parts[0].casefold() == "sources"

    def _rag_retrieve(
        self, workspace: str, run_id: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        raw_config = self.store.workspace_config(workspace).get("rag")
        config = RagProviderConfig.from_workspace(raw_config)
        max_chunks = min(max(int(arguments.get("max_chunks") or 8), 1), 20)
        return RagRetriever(self.store, config).retrieve(
            workspace,
            run_id,
            str(arguments.get("query") or ""),
            max_chunks,
        )

    def _openapi_inspect(
        self, workspace: str, run_id: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        requested = self._normalized_tool_path(arguments.get("path"))
        if self._is_source_path(requested):
            frozen = self._read_frozen_source(workspace, run_id, requested)
            source = frozen["path"]
            text = frozen["content"]
            suffix = PurePosixPath(source).suffix
        else:
            root, target = self._safe_path(workspace, requested)
            if not target.is_file():
                raise ValueError("OpenAPI source does not exist")
            source = target.relative_to(root).as_posix()
            text = target.read_text(encoding="utf-8")
            suffix = target.suffix
        try:
            payload = json.loads(text) if suffix.lower() == ".json" else yaml.safe_load(text)
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            raise ValueError("source is not a complete OpenAPI/Swagger document") from exc
        return inspect_openapi(payload, source=source).model_dump(mode="json", by_alias=True)

    def _network_capture_inspect(
        self,
        workspace: str,
        run_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        requested = self._normalized_tool_path(arguments.get("path"))
        if not self._is_source_path(requested):
            raise ValueError("network capture must belong to the frozen SourceBundle")
        frozen = self._read_frozen_source(workspace, run_id, requested)
        source = frozen["path"]
        if PurePosixPath(source).suffix.casefold() not in {".har", ".json"}:
            raise ValueError("network capture must use .har or .json")
        try:
            payload = json.loads(frozen["content"])
        except json.JSONDecodeError as exc:
            raise ValueError("network capture is not valid JSON") from exc
        return inspect_network_capture(payload, source=source).model_dump(mode="json")

    def _network_capture_live(
        self,
        _workspace: str,
        run_id: str,
        arguments: dict[str, Any],
        profile: ExecutionProfile,
    ) -> dict[str, Any]:
        if profile.environment == "analysis-only" or not profile.allow_ui_mutations:
            raise PermissionError(
                "live network capture requires an explicit UI-enabled test environment"
            )
        handler = self.handlers.get("mcp.playwright")
        owner = getattr(handler, "__self__", None)
        snapshot = getattr(owner, "snapshot", None)
        available = {tool.name for tool in snapshot.tools} if snapshot is not None else set()
        required = {"browser_network_requests", "browser_network_request"}
        missing = sorted(required - available)
        if handler is None or missing:
            raise RuntimeError(
                "live network capture requires frozen Playwright MCP tools: "
                + ", ".join(sorted(required))
            )
        catalog = inspect_playwright_network(
            handler,
            max_requests=int(arguments.get("max_requests") or 25),
            source=f"runtime/playwright-network-capture/{run_id}",
        )
        base_origin = _normalized_origin(resolve_execution_base_url(profile))
        document_origins = {
            call.origin
            for call in catalog.calls
            if call.resource_type == "document" and call.origin is not None
        }
        unexpected = sorted(origin for origin in document_origins if origin != base_origin)
        if unexpected:
            raise PermissionError(
                "Playwright navigation left the configured test origin: " + ", ".join(unexpected)
            )
        return catalog.model_dump(mode="json")

    @staticmethod
    def _validate_direct_playwright_call(
        arguments: dict[str, Any],
        profile: ExecutionProfile,
    ) -> None:
        subtool = str(arguments.get("tool") or "")
        if subtool in {"browser_network_requests", "browser_network_request"}:
            raise PermissionError(
                "raw Playwright network tools are only available through network.capture.live"
            )
        if subtool in {"browser_run_code", "browser_run_code_unsafe"}:
            raise PermissionError("arbitrary Playwright server code execution is not supported")
        nested = arguments.get("arguments")
        nested = nested if isinstance(nested, dict) else {}
        navigation_url = (
            nested.get("url")
            if subtool == "browser_navigate"
            or (subtool == "browser_tabs" and nested.get("action") == "new")
            else None
        )
        if navigation_url is None:
            return
        expected_origin = _normalized_origin(resolve_execution_base_url(profile))
        actual_origin = _normalized_origin(str(navigation_url))
        if actual_origin != expected_origin:
            raise PermissionError(
                "Playwright navigation URL must match the configured test base URL origin"
            )

    @staticmethod
    def _validate_playwright_result(result: Any, profile: ExecutionProfile) -> None:
        if not isinstance(result, dict) or not profile.base_url_env:
            return
        expected_origin = _normalized_origin(resolve_execution_base_url(profile))
        for item in result.get("content") or []:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            for line in str(item.get("text") or "").splitlines():
                if not line.startswith("- Page URL:"):
                    continue
                actual_url = line.removeprefix("- Page URL:").strip()
                if _normalized_origin(actual_url) != expected_origin:
                    raise PermissionError(
                        "Playwright page left the configured test base URL origin"
                    )

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


def resolve_execution_base_url(profile: ExecutionProfile) -> str:
    if profile.environment == "analysis-only" or not profile.base_url_env:
        raise PermissionError("Playwright requires an explicit test environment and base URL")
    base_url = os.environ.get(profile.base_url_env, "").strip()
    if not base_url:
        raise ValueError(f"base URL environment variable is not set: {profile.base_url_env}")
    _normalized_origin(base_url)
    return base_url


def _normalized_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("test base URL must be an HTTP(S) URL without embedded credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("test base URL has an invalid port") from exc
    default_port = (parsed.scheme.casefold() == "http" and port == 80) or (
        parsed.scheme.casefold() == "https" and port == 443
    )
    authority = (
        parsed.hostname.casefold()
        if port is None or default_port
        else (f"{parsed.hostname.casefold()}:{port}")
    )
    return f"{parsed.scheme.casefold()}://{authority}"
