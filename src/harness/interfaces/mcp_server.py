from __future__ import annotations

import argparse
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from harness.application.agent_request import (
    AgentRequest,
    AgentRequestCapabilities,
    AgentRequestResult,
)
from harness.domain.models import (
    ArtifactDiffResult,
    GetArtifactDiffQuery,
    RunRef,
    RunSnapshot,
)
from harness.interfaces.agent_gateway import AgentRequestGateway


def _tool_annotations(
    *,
    read_only: bool,
    destructive: bool,
    idempotent: bool,
    open_world: bool,
) -> ToolAnnotations:
    # MCP SDK releases expose different Python field names; wire aliases are stable.
    return ToolAnnotations.model_validate(
        {
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
            "idempotentHint": idempotent,
            "openWorldHint": open_world,
        }
    )


def create_mcp_server(gateway: AgentRequestGateway) -> FastMCP:
    server = FastMCP(
        "Agentic-QA",
        instructions=(
            "Analyze local UTF-8 requirements through generate_from_sources. "
            "Generated artifacts are candidates only. This server cannot approve or publish."
        ),
    )

    @server.tool(
        name="generate_from_sources",
        title="Generate QA candidates from local sources",
        description=(
            "分析白名单内的本地 UTF-8 文件或目录并生成 QA Candidate。"
            "该操作不会批准或发布产物；相同请求幂等复用同一 Run。"
        ),
        annotations=_tool_annotations(
            read_only=False,
            destructive=False,
            idempotent=True,
            open_world=True,
        ),
        structured_output=True,
    )
    def generate_from_sources(request: AgentRequest) -> AgentRequestResult:
        return gateway.generate_from_sources(request)

    @server.tool(
        name="get_run",
        title="Get an Agentic-QA run",
        description="按 workspace_id 和 run_id 只读查询 Run 状态及 Candidate。",
        annotations=_tool_annotations(
            read_only=True,
            destructive=False,
            idempotent=True,
            open_world=False,
        ),
        structured_output=True,
    )
    def get_run(ref: RunRef) -> RunSnapshot:
        return gateway.get_run(ref)

    @server.tool(
        name="get_artifact_diff",
        title="Compare artifact variants",
        description="只读比较 Candidate raw/normalized 或 published current。",
        annotations=_tool_annotations(
            read_only=True,
            destructive=False,
            idempotent=True,
            open_world=False,
        ),
        structured_output=True,
    )
    def get_artifact_diff(query: GetArtifactDiffQuery) -> ArtifactDiffResult:
        return gateway.get_artifact_diff(query)

    @server.tool(
        name="get_capabilities",
        title="Get Agentic-QA agent protocol capabilities",
        description="返回协议版本、Artifact 枚举、来源限制和审核边界。",
        annotations=_tool_annotations(
            read_only=True,
            destructive=False,
            idempotent=True,
            open_world=False,
        ),
        structured_output=True,
    )
    def get_capabilities() -> AgentRequestCapabilities:
        return gateway.get_capabilities()

    return server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic-qa-mcp")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--allow-source-root",
        action="append",
        dest="allowed_source_roots",
        help="追加允许导入的绝对路径；项目内 local-sources/requirements 始终可用",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    gateway = AgentRequestGateway(
        Path(args.repo_root),
        allowed_source_roots=[Path(item) for item in (args.allowed_source_roots or [])],
    )
    create_mcp_server(gateway).run(transport="stdio")
    return 0
