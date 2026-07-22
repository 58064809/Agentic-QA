from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from contextlib import AsyncExitStack
from queue import Queue
from threading import Thread
from typing import Any, Literal

from anyio import fail_after
from jsonschema import ValidationError, validate
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from harness.domain.security import sanitize_untrusted


class PlaywrightMCPConfig(BaseModel):
    """Workspace-owned configuration for the only supported live MCP provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agentic-qa.harness.playwright-mcp.v2"] = (
        "agentic-qa.harness.playwright-mcp.v2"
    )
    transport: Literal["stdio", "streamable_http"] = "stdio"
    command: Literal["npx", "npx.cmd"] | None = "npx"
    args: tuple[str, ...] = ("-y", "@playwright/mcp@latest")
    url: HttpUrl | None = None
    allowlist: frozenset[str] = Field(min_length=1)
    request_timeout_seconds: int = Field(default=60, ge=1, le=300)

    @model_validator(mode="before")
    @classmethod
    def apply_transport_defaults(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("transport") == "streamable_http":
            normalized = dict(value)
            normalized.setdefault("command", None)
            normalized.setdefault("args", ())
            return normalized
        return value

    @field_validator("allowlist")
    @classmethod
    def validate_allowlist(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not re.fullmatch(r"[a-z][a-z0-9_-]{0,127}", name) for name in value):
            raise ValueError("Playwright MCP allowlist contains an invalid tool name")
        return value

    @model_validator(mode="after")
    def validate_transport(self) -> PlaywrightMCPConfig:
        if self.transport == "stdio":
            if self.command is None or "@playwright/mcp@latest" not in self.args:
                raise ValueError("Playwright stdio MCP requires npx and @playwright/mcp@latest")
            if self.url is not None:
                raise ValueError("Playwright stdio MCP cannot define url")
        else:
            if self.url is None:
                raise ValueError("Playwright streamable_http MCP requires url")
            if self.url.username is not None or self.url.password is not None:
                raise ValueError("Playwright MCP URL must not contain credentials")
            if self.command is not None or self.args:
                raise ValueError("Playwright streamable_http MCP cannot define command or args")
        return self


class MCPTool(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    namespaced_name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class MCPToolSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    server: str
    transport: str
    tools: tuple[MCPTool, ...]

    @classmethod
    def freeze(
        cls,
        *,
        server: str,
        transport: str,
        listed_tools: list[dict[str, Any]],
        allowlist: set[str],
    ) -> MCPToolSnapshot:
        if transport not in {"stdio", "streamable_http"}:
            raise ValueError("MCP transport must be stdio or streamable_http")
        tools: list[MCPTool] = []
        for raw in listed_tools:
            name = str(raw.get("name") or "")
            if name not in allowlist:
                continue
            schema = raw.get("inputSchema") or raw.get("input_schema") or {}
            if not isinstance(schema, dict):
                raise ValueError(f"MCP tool schema is not an object: {name}")
            tools.append(
                MCPTool(
                    name=name,
                    namespaced_name=f"{server}.{name}",
                    description=str(raw.get("description") or "")[:2000],
                    input_schema=sanitize_untrusted(schema, max_chars=20_000),
                )
            )
        return cls(server=server, transport=transport, tools=tuple(tools))

    def parse_result(self, name: str, result: Any, *, max_chars: int = 100_000) -> Any:
        if name not in {tool.name for tool in self.tools}:
            raise PermissionError(f"MCP tool is not frozen for this run: {name}")
        return sanitize_untrusted(result, max_chars=max_chars)

    def validate_arguments(self, name: str, arguments: dict[str, Any]) -> None:
        tool = next((item for item in self.tools if item.name == name), None)
        if tool is None:
            raise PermissionError(f"MCP tool is not frozen for this run: {name}")
        try:
            validate(arguments, tool.input_schema or {"type": "object"})
        except ValidationError as exc:
            if exc.validator == "required":
                raise ValueError(
                    f"MCP tool arguments missing required fields: {exc.message}"
                ) from exc
            raise ValueError(f"MCP tool arguments are invalid: {exc.message}") from exc


class MCPBridge:
    """SDK-neutral run facade; transport setup must use the official ``mcp`` Python SDK."""

    def __init__(
        self,
        snapshot: MCPToolSnapshot,
        caller: Callable[[str, dict[str, Any]], Any],
    ) -> None:
        self.snapshot = snapshot
        self._caller = caller

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        self.snapshot.validate_arguments(name, arguments)
        try:
            result = self._caller(name, sanitize_untrusted(arguments, max_chars=50_000))
        except Exception as exc:
            raise RuntimeError(
                f"mcp_tool_error:{name}:{type(exc).__name__}:{str(exc)[:300]}"
            ) from exc
        return self.snapshot.parse_result(name, result)

    def tool_handler(self, payload: dict[str, Any]) -> Any:
        name = str(payload.get("tool") or "")
        arguments = payload.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("MCP arguments must be an object")
        return self.call(name, arguments)


class OfficialMCPClient:
    """Run-scoped official SDK client for stdio or streamable HTTP transports."""

    def __init__(
        self,
        *,
        server: str,
        transport: str,
        allowlist: set[str],
        command: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
    ) -> None:
        self.server = server
        self.transport = transport
        self.allowlist = set(allowlist)
        self.command = command
        self.args = args or []
        self.url = url
        self.snapshot: MCPToolSnapshot | None = None
        self._stack = AsyncExitStack()
        self._session: Any = None

    async def __aenter__(self) -> OfficialMCPClient:
        try:
            return await self._open()
        except BaseException:
            await self._stack.aclose()
            raise

    async def _open(self) -> OfficialMCPClient:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError as exc:  # pragma: no cover - dependency gate
            raise RuntimeError("official mcp Python SDK is not installed") from exc

        if self.transport == "stdio":
            if not self.command:
                raise ValueError("stdio MCP requires command")
            streams = await self._stack.enter_async_context(
                stdio_client(StdioServerParameters(command=self.command, args=self.args))
            )
            read, write = streams
        elif self.transport == "streamable_http":
            if not self.url:
                raise ValueError("streamable_http MCP requires url")
            streams = await self._stack.enter_async_context(streamablehttp_client(self.url))
            read, write, _ = streams
        else:
            raise ValueError("MCP transport must be stdio or streamable_http")

        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        listed = await self._session.list_tools()
        self.snapshot = MCPToolSnapshot.freeze(
            server=self.server,
            transport=self.transport,
            listed_tools=[
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema,
                }
                for tool in listed.tools
            ],
            allowlist=self.allowlist,
        )
        return self

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if self.snapshot is None or self._session is None:
            raise RuntimeError("MCP client is not initialized")
        self.snapshot.validate_arguments(name, arguments)
        try:
            result = await self._session.call_tool(name, sanitize_untrusted(arguments))
        except Exception as exc:
            raise RuntimeError(
                f"mcp_tool_error:{name}:{type(exc).__name__}:{str(exc)[:300]}"
            ) from exc
        payload = (
            result.model_dump(mode="json", by_alias=True)
            if hasattr(result, "model_dump")
            else result
        )
        return self.snapshot.parse_result(name, payload)

    async def __aexit__(self, *exc_info: Any) -> None:
        await self._stack.__aexit__(*exc_info)


class SynchronousOfficialMCPClient:
    """Synchronous, thread-safe facade that keeps one SDK session alive per run segment."""

    def __init__(self, config: PlaywrightMCPConfig) -> None:
        self.config = config
        self.snapshot: MCPToolSnapshot | None = None
        self._requests: Queue[tuple[str, dict[str, Any], Queue[tuple[bool, Any]]] | None] = Queue()
        self._ready: Queue[BaseException | None] = Queue(maxsize=1)
        self._thread: Thread | None = None
        self._shutdown_error: BaseException | None = None

    def __enter__(self) -> SynchronousOfficialMCPClient:
        self._thread = Thread(
            target=lambda: asyncio.run(self._serve()),
            name="agentic-qa-playwright-mcp",
            daemon=True,
        )
        self._thread.start()
        ready = self._ready.get()
        if ready is not None:
            self._thread.join()
            self._thread = None
            raise ready
        return self

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._thread is None or not self._thread.is_alive():
            raise RuntimeError("MCP client is not initialized")
        response: Queue[tuple[bool, Any]] = Queue(maxsize=1)
        self._requests.put((name, arguments, response))
        succeeded, value = response.get()
        if succeeded:
            return value
        raise value

    def tool_handler(self, payload: dict[str, Any]) -> Any:
        name = str(payload.get("tool") or "")
        arguments = payload.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("MCP arguments must be an object")
        return self.call(name, arguments)

    def __exit__(self, *exc_info: Any) -> None:
        if self._thread is None:
            return
        self._requests.put(None)
        self._thread.join()
        self._thread = None
        if self._shutdown_error is not None and exc_info[0] is None:
            raise RuntimeError("Playwright MCP shutdown failed") from self._shutdown_error

    async def _serve(self) -> None:
        ready = False
        client = OfficialMCPClient(
            server="playwright",
            transport=self.config.transport,
            allowlist=set(self.config.allowlist),
            command=self.config.command,
            args=list(self.config.args),
            url=str(self.config.url) if self.config.url is not None else None,
        )
        try:
            async with client:
                self.snapshot = client.snapshot
                ready = True
                self._ready.put(None)
                while True:
                    request = await asyncio.to_thread(self._requests.get)
                    if request is None:
                        return
                    name, arguments, response = request
                    try:
                        with fail_after(self.config.request_timeout_seconds):
                            result = await client.call(name, arguments)
                        response.put((True, result))
                    except BaseException as exc:
                        response.put((False, exc))
        except BaseException as exc:
            if not ready:
                self._ready.put(exc)
            else:
                self._shutdown_error = exc
