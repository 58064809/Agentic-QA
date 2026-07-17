from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agentic_qa.security import sanitize_untrusted


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
        required = tool.input_schema.get("required") or []
        missing = [field for field in required if field not in arguments]
        if missing:
            raise ValueError(f"MCP tool arguments missing required fields: {missing}")
        if tool.input_schema.get("additionalProperties") is False:
            allowed = set((tool.input_schema.get("properties") or {}).keys())
            unexpected = set(arguments) - allowed
            if unexpected:
                raise ValueError(
                    f"MCP tool arguments contain unexpected fields: {sorted(unexpected)}"
                )


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
