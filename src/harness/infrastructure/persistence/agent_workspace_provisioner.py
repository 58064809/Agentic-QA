from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from harness.application.agent_request import (
    AgentRequest,
    ImportedSourceFile,
    PreparedAgentWorkspace,
)
from harness.domain.models import normalize_workspace_id
from harness.infrastructure.persistence.common import (
    atomic_json,
    atomic_text,
    exclusive_file_lock,
)
from harness.infrastructure.persistence.workspace_repository import (
    WorkspaceFilesystemRepository,
)

UTC = timezone.utc
REPARSE_POINT = 0x400
READ_CHUNK_BYTES = 1024 * 1024
MAX_SOURCE_ROOTS = 16
MAX_FILES = 256
MAX_RECURSION_DEPTH = 16
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_RELATIVE_PATH_BYTES = 1024
IMPORT_SCHEMA = "agentic-qa.harness.agent-source-import.v1"


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_hash(payload: dict[str, Any]) -> str:
    return _sha256(_canonical_bytes(payload))


def _is_link_or_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & REPARSE_POINT
    )


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
    )


def _safe_name(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_name).strip(".-_").lower()
    return normalized[:48] or "source"


@dataclass(frozen=True)
class _SourceCandidate:
    source_root: Path
    path: Path
    logical_path: str
    identity: tuple[int, int, int, int]


class ManagedAgentWorkspaceFilesystemProvisioner:
    def __init__(
        self,
        workspaces: WorkspaceFilesystemRepository,
        *,
        allowed_source_roots: list[Path | str],
    ) -> None:
        if not allowed_source_roots:
            raise ValueError("至少配置一个 --allow-source-root 才能导入本地来源")
        self.workspaces = workspaces
        self.allowed_source_roots = tuple(
            self._validated_allowed_root(Path(item)) for item in allowed_source_roots
        )

    def prepare(self, request: AgentRequest) -> PreparedAgentWorkspace:
        self.workspaces.root.mkdir(parents=True, exist_ok=True)
        candidates = self._collect_candidates(request.source_paths)
        scan_root = Path(tempfile.mkdtemp(prefix=".agent-source-scan-", dir=self.workspaces.root))
        try:
            imported = self._copy_and_hash_candidates(candidates, scan_root)
            self._verify_tree_stable(request.source_paths, candidates)
            request_key = self._request_key(request, imported)
            workspace_id = request.workspace_id or self._automatic_workspace_id(
                request.source_paths[0],
                request_key,
            )
            workspace_id = normalize_workspace_id(workspace_id)
            run_id = f"run-request-{request_key.removeprefix('sha256:')[:24]}"
            manifest = self._manifest_payload(
                request=request,
                request_key=request_key,
                workspace_id=workspace_id,
                run_id=run_id,
                files=imported,
            )
            manifest_sha256 = _canonical_hash(manifest)
            prepared = PreparedAgentWorkspace(
                request_key=request_key,
                workspace_id=workspace_id,
                run_id=run_id,
                import_manifest_sha256=manifest_sha256,
                files=imported,
                total_bytes=sum(item.size_bytes for item in imported),
            )
            self._install_workspace(prepared, request, manifest, scan_root)
            return prepared
        finally:
            self._remove_temporary_tree(scan_root)

    @contextmanager
    def request_lock(self, prepared: PreparedAgentWorkspace) -> Iterator[None]:
        key = prepared.request_key.removeprefix("sha256:")
        workspace = self.workspaces.require_workspace(prepared.workspace_id)
        with exclusive_file_lock(workspace / "requests" / ".locks" / f"{key}.lock"):
            yield

    def _validated_allowed_root(self, root: Path) -> Path:
        if not root.is_absolute():
            raise ValueError(f"allow-source-root 必须是绝对路径: {root}")
        try:
            absolute = root.resolve(strict=True)
            info = absolute.lstat()
        except OSError as exc:
            raise ValueError(f"allow-source-root 不可访问: {root}") from exc
        if _is_link_or_reparse(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"allow-source-root 必须是非链接目录: {root}")
        return absolute

    def _collect_candidates(self, values: list[str]) -> list[_SourceCandidate]:
        if len(values) > MAX_SOURCE_ROOTS:
            raise ValueError(f"source_paths 超过限制: {MAX_SOURCE_ROOTS}")
        roots = [self._validated_requested_path(value) for value in values]
        if len({os.path.normcase(str(item)) for item in roots}) != len(roots):
            raise ValueError("source_paths 解析后存在重复路径")
        candidates: list[_SourceCandidate] = []
        seen_files: set[str] = set()
        seen_logical: set[str] = set()
        for source_root in sorted(roots, key=lambda item: os.path.normcase(str(item))):
            alias_hash = hashlib.sha256(
                os.path.normcase(str(source_root)).encode("utf-8")
            ).hexdigest()[:8]
            alias = f"{_safe_name(source_root.stem or source_root.name)}-{alias_hash}"
            info = source_root.lstat()
            if stat.S_ISREG(info.st_mode):
                entries = [(source_root, Path(source_root.name), 0)]
            elif stat.S_ISDIR(info.st_mode):
                entries = list(self._walk_directory(source_root))
            else:
                raise ValueError(f"来源不是普通文件或目录: {source_root.name}")
            for path, relative, _depth in entries:
                canonical = os.path.normcase(str(path))
                if canonical in seen_files:
                    raise ValueError(f"来源文件被多个输入路径重复包含: {path.name}")
                seen_files.add(canonical)
                logical = unicodedata.normalize(
                    "NFC",
                    (Path("sources") / "imports" / alias / relative).as_posix(),
                )
                if len(logical.encode("utf-8")) > MAX_RELATIVE_PATH_BYTES:
                    raise ValueError(f"来源相对路径超过限制: {logical}")
                if any(ord(character) < 32 for character in logical):
                    raise ValueError(f"来源相对路径包含控制字符: {logical!r}")
                folded = logical.casefold()
                if folded in seen_logical:
                    raise ValueError(f"来源路径大小写折叠冲突: {logical}")
                seen_logical.add(folded)
                file_info = path.lstat()
                if _is_link_or_reparse(file_info) or not stat.S_ISREG(file_info.st_mode):
                    raise ValueError(f"来源包含链接或非普通文件: {path.name}")
                candidates.append(
                    _SourceCandidate(
                        source_root=source_root,
                        path=path,
                        logical_path=logical,
                        identity=_file_identity(file_info),
                    )
                )
                if len(candidates) > MAX_FILES:
                    raise ValueError(f"来源文件数量超过限制: {MAX_FILES}")
        if not candidates:
            raise ValueError("来源目录中没有可导入的 UTF-8 文本文件")
        return sorted(candidates, key=lambda item: item.logical_path)

    def _validated_requested_path(self, value: str) -> Path:
        requested = Path(value)
        if not requested.is_absolute():
            raise ValueError(f"source path 必须是绝对路径: {value}")
        absolute = Path(os.path.abspath(requested))
        allowed = next(
            (root for root in self.allowed_source_roots if self._is_relative_to(absolute, root)),
            None,
        )
        if allowed is None:
            raise PermissionError(f"source path 不在 allow-source-root 内: {requested.name}")
        self._reject_linked_path(allowed, absolute)
        return absolute

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            common = os.path.commonpath([os.path.normcase(str(path)), os.path.normcase(str(root))])
        except ValueError:
            return False
        return common == os.path.normcase(str(root))

    @staticmethod
    def _reject_linked_path(root: Path, target: Path) -> None:
        current = root
        try:
            relative = target.relative_to(root)
        except ValueError as exc:
            raise PermissionError(f"source path 越界: {target.name}") from exc
        for part in relative.parts:
            current = current / part
            try:
                info = current.lstat()
            except OSError as exc:
                raise ValueError(f"source path 不可访问: {current.name}") from exc
            if _is_link_or_reparse(info):
                raise ValueError(f"source path 包含链接或 reparse point: {current.name}")

    def _walk_directory(self, root: Path) -> Iterator[tuple[Path, Path, int]]:
        stack: list[tuple[Path, Path, int]] = [(root, Path(), 0)]
        while stack:
            directory, relative, depth = stack.pop()
            if depth > MAX_RECURSION_DEPTH:
                raise ValueError(f"来源目录递归深度超过限制: {MAX_RECURSION_DEPTH}")
            try:
                entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
            except OSError as exc:
                raise ValueError(f"无法扫描来源目录: {directory.name}") from exc
            directories: list[tuple[Path, Path, int]] = []
            for entry in entries:
                path = Path(entry.path)
                info = path.lstat()
                if _is_link_or_reparse(info):
                    raise ValueError(f"来源目录包含链接或 reparse point: {entry.name}")
                child_relative = relative / entry.name
                if stat.S_ISDIR(info.st_mode):
                    directories.append((path, child_relative, depth + 1))
                elif stat.S_ISREG(info.st_mode):
                    yield path, child_relative, depth
                else:
                    raise ValueError(f"来源目录包含非普通文件: {entry.name}")
            stack.extend(reversed(directories))

    def _copy_and_hash_candidates(
        self,
        candidates: list[_SourceCandidate],
        scan_root: Path,
    ) -> list[ImportedSourceFile]:
        imported: list[ImportedSourceFile] = []
        total_bytes = 0
        for candidate in candidates:
            before = candidate.path.lstat()
            if _file_identity(before) != candidate.identity:
                raise RuntimeError(f"来源文件在扫描后发生变化: {candidate.path.name}")
            if before.st_size > MAX_FILE_BYTES:
                raise ValueError(f"来源文件超过 {MAX_FILE_BYTES} bytes: {candidate.path.name}")
            total_bytes += before.st_size
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError(f"来源总量超过 {MAX_TOTAL_BYTES} bytes")
            destination = scan_root / Path(candidate.logical_path).relative_to("sources")
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            decoder_bytes = bytearray()
            with candidate.path.open("rb") as source, destination.open("xb") as target:
                opened = os.fstat(source.fileno())
                if _file_identity(opened) != candidate.identity:
                    raise RuntimeError(f"来源文件打开时身份变化: {candidate.path.name}")
                while chunk := source.read(READ_CHUNK_BYTES):
                    digest.update(chunk)
                    decoder_bytes.extend(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
                closed = os.fstat(source.fileno())
            after = candidate.path.lstat()
            if (
                _is_link_or_reparse(after)
                or not stat.S_ISREG(after.st_mode)
                or _file_identity(closed) != candidate.identity
                or _file_identity(after) != candidate.identity
            ):
                raise RuntimeError(f"来源文件读取期间发生变化: {candidate.path.name}")
            try:
                text = bytes(decoder_bytes).decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ValueError(f"来源文件不是完整 UTF-8 文本: {candidate.path.name}") from exc
            if "\x00" in text:
                raise ValueError(f"来源文件包含 NUL 字符: {candidate.path.name}")
            imported.append(
                ImportedSourceFile(
                    logical_path=candidate.logical_path,
                    raw_sha256=f"sha256:{digest.hexdigest()}",
                    size_bytes=before.st_size,
                )
            )
        return imported

    def _verify_tree_stable(
        self,
        values: list[str],
        expected: list[_SourceCandidate],
    ) -> None:
        current = self._collect_candidates(values)
        expected_state = {(item.logical_path, item.identity) for item in expected}
        current_state = {(item.logical_path, item.identity) for item in current}
        if current_state != expected_state:
            raise RuntimeError("来源目录在导入期间发生变化")

    @staticmethod
    def _request_key(
        request: AgentRequest,
        files: list[ImportedSourceFile],
    ) -> str:
        payload = {
            "schema": request.schema_version,
            "request_id": request.request_id,
            "goal": request.goal,
            "expected_artifacts": request.expected_artifacts,
            "quality_policies": request.quality_policies,
            "sources": [item.model_dump(mode="json") for item in files],
        }
        return _canonical_hash(payload)

    @staticmethod
    def _automatic_workspace_id(first_source: str, request_key: str) -> str:
        base = _safe_name(Path(first_source).stem or Path(first_source).name)
        suffix = request_key.removeprefix("sha256:")[:12]
        return f"qa-{base}-{suffix}"[:128]

    @staticmethod
    def _manifest_payload(
        *,
        request: AgentRequest,
        request_key: str,
        workspace_id: str,
        run_id: str,
        files: list[ImportedSourceFile],
    ) -> dict[str, Any]:
        return {
            "schema_version": IMPORT_SCHEMA,
            "request_key": request_key,
            "workspace_id": workspace_id,
            "run_id": run_id,
            "request": {
                "schema_version": request.schema_version,
                "request_id": request.request_id,
                "goal": request.goal,
                "expected_artifacts": request.expected_artifacts,
                "quality_policies": request.quality_policies,
            },
            "source_import": {
                "file_count": len(files),
                "total_bytes": sum(item.size_bytes for item in files),
                "files": [item.model_dump(mode="json") for item in files],
            },
        }

    def _install_workspace(
        self,
        prepared: PreparedAgentWorkspace,
        request: AgentRequest,
        manifest: dict[str, Any],
        scan_root: Path,
    ) -> None:
        final = self.workspaces.workspace_path(prepared.workspace_id)
        with exclusive_file_lock(self.workspaces.root / ".agent-request-workspaces.lock"):
            if final.exists():
                self._validate_existing_workspace(final, prepared, manifest)
                return
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".{prepared.workspace_id}.staging-",
                    dir=self.workspaces.root,
                )
            )
            try:
                for relative in (
                    "sources",
                    "runs",
                    "candidates",
                    "reviews",
                    "published",
                    "memory",
                    "requests",
                ):
                    (staging / relative).mkdir()
                shutil.copytree(scan_root, staging / "sources", dirs_exist_ok=True)
                atomic_text(
                    staging / "workspace.yml",
                    yaml.safe_dump(
                        {
                            "schema_version": "agentic-qa.harness.workspace.v2",
                            "id": prepared.workspace_id,
                            "created_at": datetime.now(tz=UTC).isoformat(),
                            "quality_policies": request.quality_policies,
                            "rag": {"provider": "local-lexical"},
                            "execution": {"environments": {}},
                        },
                        allow_unicode=True,
                        sort_keys=False,
                    ),
                )
                atomic_json(staging / "agent-request.json", manifest)
                self._validate_imported_files(staging, prepared.files)
                self._sync_tree(staging)
                os.replace(staging, final)
                self._sync_directory(self.workspaces.root)
            finally:
                if staging.exists():
                    self._remove_temporary_tree(staging)

    def _validate_existing_workspace(
        self,
        workspace: Path,
        prepared: PreparedAgentWorkspace,
        expected_manifest: dict[str, Any],
    ) -> None:
        manifest_path = workspace / "agent-request.json"
        if not manifest_path.is_file():
            raise FileExistsError(
                f"workspace 已存在且不由 Agent Request 管理: {prepared.workspace_id}"
            )
        try:
            actual = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("托管 workspace 的 agent-request.json 无效") from exc
        if actual != expected_manifest:
            raise FileExistsError(f"workspace 已被其他 Agent Request 占用: {prepared.workspace_id}")
        config = self.workspaces.workspace_config(prepared.workspace_id)
        if config.get("quality_policies") != expected_manifest["request"]["quality_policies"]:
            raise RuntimeError("托管 workspace 的 quality_policies 与 Agent Request 不一致")
        self._validate_imported_files(workspace, prepared.files)

    @staticmethod
    def _validate_imported_files(
        workspace: Path,
        files: list[ImportedSourceFile],
    ) -> None:
        expected = {item.logical_path.removeprefix("sources/"): item for item in files}
        source_root = workspace / "sources"
        actual_paths = {
            path.relative_to(source_root).as_posix()
            for path in source_root.rglob("*")
            if path.is_file()
        }
        if actual_paths != set(expected):
            raise RuntimeError("托管 workspace 的来源文件集合与 import manifest 不一致")
        for relative, item in expected.items():
            path = source_root / relative
            info = path.lstat()
            if _is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
                raise RuntimeError(f"托管来源不是普通文件: {relative}")
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                while chunk := handle.read(READ_CHUNK_BYTES):
                    digest.update(chunk)
            if f"sha256:{digest.hexdigest()}" != item.raw_sha256:
                raise RuntimeError(f"托管来源 hash 校验失败: {relative}")

    @staticmethod
    def _sync_tree(root: Path) -> None:
        for path in root.rglob("*"):
            if path.is_file():
                with path.open("r+b") as handle:
                    os.fsync(handle.fileno())
        for path in sorted(
            (item for item in root.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            ManagedAgentWorkspaceFilesystemProvisioner._sync_directory(path)
        ManagedAgentWorkspaceFilesystemProvisioner._sync_directory(root)

    @staticmethod
    def _sync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _remove_temporary_tree(self, path: Path) -> None:
        if not path.exists():
            return
        resolved = path.resolve()
        root = self.workspaces.root.resolve()
        if resolved.parent != root or not resolved.name.startswith("."):
            raise RuntimeError(f"拒绝删除非托管临时目录: {resolved}")
        shutil.rmtree(resolved)
