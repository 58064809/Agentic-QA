from __future__ import annotations

import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from harness.application.agent_request import (
    AgentNextAction,
    AgentRequest,
    AgentRequestService,
    ImportedSourceFile,
    PreparedAgentWorkspace,
)
from harness.bootstrap import build_application
from harness.domain.models import ExecutionProfile, RunSnapshot, StartRunCommand
from harness.infrastructure.persistence.agent_workspace_provisioner import (
    ManagedAgentWorkspaceFilesystemProvisioner,
)
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.persistence.workspace_repository import (
    WorkspaceFilesystemRepository,
)
from harness.interfaces import cli
from harness.interfaces.agent_gateway import AgentRequestGateway
from harness.interfaces.cli import _load_agent_request
from harness.interfaces.mcp_server import create_mcp_server
from harness.testing.evals import recorded_model_gateway


def _request(source: Path, *, workspace_id: str | None = None) -> AgentRequest:
    return AgentRequest(
        workspace_id=workspace_id,
        goal="分析需求并生成测试用例",
        source_paths=[str(source)],
    )


def _provisioner(repo: Path, allowed: Path) -> ManagedAgentWorkspaceFilesystemProvisioner:
    return ManagedAgentWorkspaceFilesystemProvisioner(
        WorkspaceFilesystemRepository(repo),
        allowed_source_roots=[allowed],
    )


def test_agent_request_yaml_and_json_are_equivalent(tmp_path: Path) -> None:
    payload = {
        "schema_version": "agentic-qa.harness.agent-request.v1",
        "goal": "生成测试用例",
        "source_paths": [str((tmp_path / "requirements.md").resolve())],
    }
    yaml_path = tmp_path / "request.yml"
    json_path = tmp_path / "request.json"
    yaml_path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    assert _load_agent_request(yaml_path) == _load_agent_request(json_path)


def test_mcp_exposes_only_generation_and_read_queries() -> None:
    server = create_mcp_server(SimpleNamespace())
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    assert set(tools) == {
        "generate_from_sources",
        "get_run",
        "get_artifact_diff",
        "get_capabilities",
    }
    assert not set(tools) & {"review", "review_run", "approve", "promote"}
    generate = tools["generate_from_sources"].annotations.model_dump(by_alias=True)
    assert generate["readOnlyHint"] is False
    assert generate["destructiveHint"] is False
    assert generate["idempotentHint"] is True
    get_run = tools["get_run"].annotations.model_dump(by_alias=True)
    assert get_run["readOnlyHint"] is True
    request_properties = tools["generate_from_sources"].inputSchema["$defs"]["AgentRequest"][
        "properties"
    ]
    assert "Absolute UTF-8 text" in request_properties["source_paths"]["description"]
    assert not set(request_properties) & {"review", "approve", "promote"}


def test_agent_gateway_get_run_uses_read_only_repository_path() -> None:
    calls: list[object] = []
    snapshot = SimpleNamespace(run_id="run-1")

    class Application:
        def get_run_read_only(self, ref):
            calls.append(ref)
            return snapshot

    gateway = AgentRequestGateway(
        ".",
        allowed_source_roots=[],
        application=Application(),
    )

    result = gateway.get_run(SimpleNamespace(workspace_id="managed", run_id="run-1"))

    assert result is snapshot
    assert len(calls) == 1


def test_mcp_stdio_server_lists_restricted_tools(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    async def scenario() -> set[str]:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "harness",
                "--repo-root",
                str(tmp_path / "repo"),
                "mcp",
                "serve",
                "--allow-source-root",
                str(allowed),
            ],
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.list_tools()
                return {tool.name for tool in response.tools}

    assert asyncio.run(scenario()) == {
        "generate_from_sources",
        "get_run",
        "get_artifact_diff",
        "get_capabilities",
    }


def test_provisioner_imports_directory_without_persisting_absolute_paths(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "requirements"
    nested = allowed / "release"
    nested.mkdir(parents=True)
    (nested / "prd.md").write_text("# 需求\n\n支持会员登录。\n", encoding="utf-8")
    (nested / "api.yaml").write_text("openapi: 3.1.0\n", encoding="utf-8")
    repo = tmp_path / "repo"

    prepared = _provisioner(repo, allowed).prepare(_request(nested))

    assert len(prepared.files) == 2
    assert all(item.logical_path.startswith("sources/imports/") for item in prepared.files)
    workspace = repo / "workspaces" / prepared.workspace_id
    manifest_text = (workspace / "agent-request.json").read_text(encoding="utf-8")
    assert str(allowed) not in manifest_text
    assert all((workspace / item.logical_path).is_file() for item in prepared.files)


def test_provisioner_reuses_identical_managed_workspace(tmp_path: Path) -> None:
    allowed = tmp_path / "requirements"
    allowed.mkdir()
    source = allowed / "prd.md"
    source.write_text("# 需求\n\n生成测试用例。\n", encoding="utf-8")
    provisioner = _provisioner(tmp_path / "repo", allowed)
    request = _request(source)

    first = provisioner.prepare(request)
    second = provisioner.prepare(request)

    assert second == first


def test_source_content_change_changes_request_key_and_workspace(tmp_path: Path) -> None:
    allowed = tmp_path / "requirements"
    allowed.mkdir()
    source = allowed / "prd.md"
    source.write_text("版本一\n", encoding="utf-8")
    provisioner = _provisioner(tmp_path / "repo", allowed)

    first = provisioner.prepare(_request(source))
    source.write_text("版本二\n", encoding="utf-8")
    second = provisioner.prepare(_request(source))

    assert second.request_key != first.request_key
    assert second.workspace_id != first.workspace_id


def test_explicit_workspace_cannot_be_reused_by_different_request(tmp_path: Path) -> None:
    allowed = tmp_path / "requirements"
    allowed.mkdir()
    source = allowed / "prd.md"
    source.write_text("版本一\n", encoding="utf-8")
    provisioner = _provisioner(tmp_path / "repo", allowed)
    provisioner.prepare(_request(source, workspace_id="managed"))
    source.write_text("版本二\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="其他 Agent Request"):
        provisioner.prepare(_request(source, workspace_id="managed"))


def test_import_rejects_path_outside_allowed_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("需求\n", encoding="utf-8")

    with pytest.raises(PermissionError, match="allow-source-root"):
        _provisioner(tmp_path / "repo", allowed).prepare(_request(outside))


def test_import_requires_at_least_one_allowed_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="allow-source-root"):
        ManagedAgentWorkspaceFilesystemProvisioner(
            WorkspaceFilesystemRepository(tmp_path / "repo"),
            allowed_source_roots=[],
        )


def test_import_rejects_casefold_path_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    first = allowed / "one.md"
    second = allowed / "two.md"
    first.write_text("一\n", encoding="utf-8")
    second.write_text("二\n", encoding="utf-8")
    provisioner = _provisioner(tmp_path / "repo", allowed)
    monkeypatch.setattr(
        provisioner,
        "_walk_directory",
        lambda _root: iter(
            [
                (first, Path("Rule.md"), 0),
                (second, Path("rule.md"), 0),
            ]
        ),
    )

    with pytest.raises(ValueError, match="大小写折叠冲突"):
        provisioner.prepare(_request(allowed))


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"\xff\xfe", "UTF-8"),
        (b"requirement\x00text", "NUL"),
    ],
)
def test_import_rejects_non_text_sources(
    tmp_path: Path,
    content: bytes,
    message: str,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "bad.bin"
    source.write_bytes(content)

    with pytest.raises(ValueError, match=message):
        _provisioner(tmp_path / "repo", allowed).prepare(_request(source))


def test_import_rejects_file_and_total_budgets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness.infrastructure.persistence import agent_workspace_provisioner as module

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "large.md"
    source.write_text("12345", encoding="utf-8")
    monkeypatch.setattr(module, "MAX_FILE_BYTES", 4)

    with pytest.raises(ValueError, match="来源文件超过"):
        _provisioner(tmp_path / "repo", allowed).prepare(_request(source))


def test_import_rejects_total_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness.infrastructure.persistence import agent_workspace_provisioner as module

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "one.md").write_text("123", encoding="utf-8")
    (allowed / "two.md").write_text("456", encoding="utf-8")
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", 5)

    with pytest.raises(ValueError, match="来源总量超过"):
        _provisioner(tmp_path / "repo", allowed).prepare(_request(allowed))


def test_import_rejects_recursion_depth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness.infrastructure.persistence import agent_workspace_provisioner as module

    allowed = tmp_path / "allowed"
    nested = allowed / "one" / "two"
    nested.mkdir(parents=True)
    (nested / "prd.md").write_text("需求\n", encoding="utf-8")
    monkeypatch.setattr(module, "MAX_RECURSION_DEPTH", 1)

    with pytest.raises(ValueError, match="递归深度"):
        _provisioner(tmp_path / "repo", allowed).prepare(_request(allowed))


def test_import_rejects_file_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness.infrastructure.persistence import agent_workspace_provisioner as module

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "one.md").write_text("1\n", encoding="utf-8")
    (allowed / "two.md").write_text("2\n", encoding="utf-8")
    monkeypatch.setattr(module, "MAX_FILES", 1)

    with pytest.raises(ValueError, match="文件数量"):
        _provisioner(tmp_path / "repo", allowed).prepare(_request(allowed))


def test_import_detects_file_replacement_after_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "prd.md"
    source.write_text("原始需求\n", encoding="utf-8")
    provisioner = _provisioner(tmp_path / "repo", allowed)
    original = provisioner._copy_and_hash_candidates

    def replace_then_copy(candidates, scan_root):
        source.write_text("替换后的需求\n", encoding="utf-8")
        return original(candidates, scan_root)

    monkeypatch.setattr(provisioner, "_copy_and_hash_candidates", replace_then_copy)

    with pytest.raises(RuntimeError, match="发生变化"):
        provisioner.prepare(_request(source))


def test_atomic_workspace_failure_leaves_no_visible_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "prd.md"
    source.write_text("需求\n", encoding="utf-8")
    repo = tmp_path / "repo"
    provisioner = _provisioner(repo, allowed)
    monkeypatch.setattr(
        provisioner,
        "_sync_tree",
        lambda _root: (_ for _ in ()).throw(OSError("fault injection")),
    )

    with pytest.raises(OSError, match="fault injection"):
        provisioner.prepare(_request(source, workspace_id="atomic"))

    assert not (repo / "workspaces" / "atomic").exists()
    assert not list((repo / "workspaces").glob(".atomic.staging-*"))


def test_concurrent_identical_requests_prepare_one_workspace(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "prd.md"
    source.write_text("并发需求\n", encoding="utf-8")
    provisioner = _provisioner(tmp_path / "repo", allowed)
    request = _request(source)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: provisioner.prepare(request), range(2)))

    assert results[0] == results[1]
    workspace_root = tmp_path / "repo" / "workspaces"
    visible = [
        path for path in workspace_root.iterdir() if path.is_dir() and not path.name.startswith(".")
    ]
    assert [path.name for path in visible] == [results[0].workspace_id]


def test_import_rejects_symlink(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("创建 symlink 通常需要 Windows 开发者权限")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    real = allowed / "real.md"
    real.write_text("需求\n", encoding="utf-8")
    link = allowed / "linked.md"
    link.symlink_to(real)

    with pytest.raises(ValueError, match="链接"):
        _provisioner(tmp_path / "repo", allowed).prepare(_request(link))


def test_cli_request_run_uses_agent_request_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "prd.md"
    source.write_text("需求\n", encoding="utf-8")
    request_path = tmp_path / "request.yml"
    request_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "agentic-qa.harness.agent-request.v1",
                "goal": "生成测试用例",
                "source_paths": [str(source)],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    captured: list[AgentRequest] = []

    class Gateway:
        def __init__(self, _repo_root: Path, *, allowed_source_roots: list[Path]) -> None:
            assert allowed_source_roots == [allowed]

        def generate_from_sources(self, request: AgentRequest):
            captured.append(request)
            return {"workspace_id": "managed", "run_id": "run-request-1"}

    monkeypatch.setattr(cli, "AgentRequestGateway", Gateway)

    exit_code = cli.main(
        [
            "--repo-root",
            str(tmp_path / "repo"),
            "request",
            "run",
            str(request_path),
            "--allow-source-root",
            str(allowed),
        ]
    )

    assert exit_code == 0
    assert captured == [_load_agent_request(request_path)]
    assert json.loads(capsys.readouterr().out)["workspace_id"] == "managed"


def test_agent_request_end_to_end_is_idempotent_and_stops_at_review(
    tmp_path: Path,
) -> None:
    allowed = tmp_path / "requirements"
    allowed.mkdir()
    source = allowed / "prd.md"
    original = "# 需求\n\n支持账号登录。\n"
    source.write_text(original, encoding="utf-8")
    repo = tmp_path / "repo"
    application = build_application(
        repo,
        model_gateway=recorded_model_gateway(),
        allowed_source_roots=[allowed],
    )
    gateway = AgentRequestGateway(
        repo,
        allowed_source_roots=[allowed],
        application=application,
    )
    request = _request(source)

    first = gateway.generate_from_sources(request)
    second = gateway.generate_from_sources(request)

    assert second.run_id == first.run_id
    assert first.status == "needs_human_review"
    assert first.next_action == AgentNextAction.HUMAN_REVIEW_REQUIRED
    assert [item.artifact for item in first.candidates] == ["testcases"]
    assert not list((repo / "workspaces" / first.workspace_id / "published").glob("*"))

    source.write_text("后来修改的需求\n", encoding="utf-8")
    bundle = FilesystemStore(repo).load_source_bundle(first.workspace_id, first.run_id)
    assert bundle.documents[0].text.splitlines() == original.splitlines()


def test_concurrent_agent_requests_create_one_run(tmp_path: Path) -> None:
    allowed = tmp_path / "requirements"
    allowed.mkdir()
    source = allowed / "prd.md"
    source.write_text("# 需求\n\n并发生成测试用例。\n", encoding="utf-8")
    repo = tmp_path / "repo"
    application = build_application(
        repo,
        model_gateway=recorded_model_gateway(),
        allowed_source_roots=[allowed],
    )
    gateway = AgentRequestGateway(
        repo,
        allowed_source_roots=[allowed],
        application=application,
    )
    request = _request(source)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: gateway.generate_from_sources(request), range(2)))

    assert results[0].run_id == results[1].run_id
    runs = repo / "workspaces" / results[0].workspace_id / "runs"
    assert [path.name for path in runs.iterdir() if path.is_dir()] == [results[0].run_id]


def test_recoverable_request_uses_workflow_resume() -> None:
    request = AgentRequest(
        goal="生成测试用例",
        source_paths=["D:/requirements/prd.md"],
    )
    prepared = PreparedAgentWorkspace(
        request_key=f"sha256:{'a' * 64}",
        workspace_id="managed",
        run_id="run-request-aaaaaaaaaaaaaaaaaaaaaaaa",
        import_manifest_sha256=f"sha256:{'b' * 64}",
        files=[
            ImportedSourceFile(
                logical_path="sources/imports/prd/prd.md",
                raw_sha256=f"sha256:{'c' * 64}",
                size_bytes=1,
            )
        ],
        total_bytes=1,
    )
    command = StartRunCommand(
        workspace_id="managed",
        goal=request.goal,
        expected_artifacts=["testcases"],
        execution_profile=ExecutionProfile(),
    )
    snapshot = RunSnapshot(
        run_id=prepared.run_id,
        workspace_id="managed",
        status="recoverable",
        request=command,
    )

    class Provisioner:
        def prepare(self, _request: AgentRequest) -> PreparedAgentWorkspace:
            return prepared

        @contextmanager
        def request_lock(self, _prepared: PreparedAgentWorkspace):
            yield

    class Runs:
        def load_snapshot(self, _workspace: str, _run_id: str) -> RunSnapshot:
            return snapshot

    class Workflow:
        resumed = False

        def resume(self, existing: RunSnapshot) -> RunSnapshot:
            self.resumed = True
            existing.status = "needs_human_review"
            return existing

    workflow = Workflow()
    service = AgentRequestService(
        provisioner=Provisioner(),
        runs=Runs(),
        workflow=workflow,
        quality_policies=SimpleNamespace(require=lambda _names: ()),
    )

    result = service.submit(request)

    assert workflow.resumed
    assert result.next_action == AgentNextAction.HUMAN_REVIEW_REQUIRED
