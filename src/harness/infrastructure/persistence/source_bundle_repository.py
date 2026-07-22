from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from harness.application.source import (
    SourceBundle,
    SourceCompleteness,
    SourceDocument,
    SourceIngestionLimits,
    SourceIssue,
    SourceIssueSeverity,
)
from harness.infrastructure.persistence.common import atomic_json, atomic_text, exclusive_file_lock
from harness.infrastructure.persistence.workspace_repository import WorkspaceFilesystemRepository

PARSER_VERSION = "2.1.0"
HASH_CHUNK_BYTES = 1024 * 1024
KEYWORDS = ("配置", "档位", "对应关系", "规则表", "枚举")
REPARSE_POINT = 0x400
TABLE_DELIMITER = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")
ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+|$)(.*?)(?:[ \t]+#+[ \t]*)?$")
SETEXT_MARKER = re.compile(r"^ {0,3}(?:=+|-+)\s*$")
NUMBERED_COLON_HEADING = re.compile(
    r"^ {0,3}(?:\d+(?:\.\d+)*|[一二三四五六七八九十百]+)[、.)）]\s*\S.{0,76}[：:]\s*$"
)


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return _sha256(encoded)


def _issue_payload(issue: SourceIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "severity": issue.severity.value,
        "path": issue.path,
        "details": issue.details,
    }


def _is_heading(lines: list[str], index: int) -> tuple[bool, str, int]:
    line = lines[index]
    atx = ATX_HEADING.fullmatch(line)
    if atx:
        title = atx.group(2).strip()
        return bool(title), title, 1
    if index + 1 < len(lines):
        marker = lines[index + 1]
        if line.strip() and SETEXT_MARKER.fullmatch(marker):
            return True, line.strip(), 2
    stripped = line.strip()
    if len(stripped) <= 80 and stripped.endswith(("：", ":")):
        if NUMBERED_COLON_HEADING.fullmatch(line) or not stripped[0].isdigit():
            return True, stripped.rstrip("：:"), 1
    return False, "", 1


def _visible_markdown_lines(text: str) -> list[str]:
    visible: list[str] = []
    fence: str | None = None
    in_comment = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            visible.append("")
            continue
        if stripped.startswith(("```", "~~~")):
            fence = stripped[:3]
            visible.append("")
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
            visible.append("")
            continue
        if "<!--" in line:
            if "-->" not in line.split("<!--", 1)[1]:
                in_comment = True
            visible.append("")
            continue
        if stripped.startswith(">"):
            visible.append("")
            continue
        visible.append(line)
    return visible


def _critical_structure_issues(path: str, text: str, truncated: bool) -> list[SourceIssue]:
    lines = _visible_markdown_lines(text)
    headings: list[tuple[int, str, int]] = []
    index = 0
    while index < len(lines):
        matched, title, width = _is_heading(lines, index)
        if matched:
            headings.append((index, title, width))
        index += max(width, 1)
    issues: list[SourceIssue] = []
    for position, (start, title, width) in enumerate(headings):
        if not any(keyword in title for keyword in KEYWORDS):
            continue
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body = [line.strip() for line in lines[start + width : end] if line.strip()]
        if _has_section_content(body):
            continue
        if truncated and end == len(lines):
            issues.append(
                SourceIssue(
                    code="structure_check_inconclusive",
                    path=path,
                    message="关键章节位于截断边界，无法确认结构是否完整",
                    details={"heading": title, "line": start + 1},
                )
            )
        else:
            issues.append(
                SourceIssue(
                    code="suspected_missing_structure",
                    severity=SourceIssueSeverity.BLOCKER,
                    path=path,
                    message="关键章节标题后缺少正文、列表或有效表格数据",
                    details={"heading": title, "line": start + 1},
                )
            )
    return issues


def _has_section_content(lines: list[str]) -> bool:
    visible = [line for line in lines if line and line != "---"]
    non_table = [line for line in visible if "|" not in line]
    if non_table:
        return True
    for index in range(1, len(visible) - 1):
        if TABLE_DELIMITER.fullmatch(visible[index]):
            header = visible[index - 1]
            data = visible[index + 1]
            if "|" in header and "|" in data and not TABLE_DELIMITER.fullmatch(data):
                return True
    return False


class SourceBundleFilesystemRepository:
    def __init__(
        self,
        workspaces: WorkspaceFilesystemRepository,
        limits: SourceIngestionLimits | None = None,
    ) -> None:
        self.workspaces = workspaces
        self.limits = limits or SourceIngestionLimits()

    def create_source_bundle(self, workspace: str, run_id: str) -> SourceBundle:
        run_root = self.workspaces.require_workspace(workspace) / "runs" / run_id
        manifest_path = run_root / "source-bundle.json"
        with exclusive_file_lock(run_root / ".source-bundle.lock"):
            if manifest_path.exists():
                return self.load_source_bundle(workspace, run_id)
            return self._create_source_bundle(workspace, run_id, run_root, manifest_path)

    def _create_source_bundle(
        self,
        workspace: str,
        run_id: str,
        run_root: Path,
        manifest_path: Path,
    ) -> SourceBundle:
        source_root = self.workspaces.require_workspace(workspace) / "sources"
        documents: list[SourceDocument] = []
        candidates, scan_issues = self._scan_source_tree(source_root)
        bundle_issues: list[SourceIssue] = list(scan_issues)
        parsed_remaining = self.limits.max_parsed_characters
        hash_remaining = self.limits.max_total_hash_bytes
        seen_paths: set[str] = set()
        regular_count = 0
        for candidate in candidates:
            try:
                relative = unicodedata.normalize(
                    "NFC",
                    candidate.relative_to(self.workspaces.require_workspace(workspace)).as_posix(),
                )
                info = candidate.lstat()
            except OSError as exc:
                bundle_issues.append(
                    SourceIssue(
                        code="source_read_failed",
                        path=str(candidate.name),
                        message="无法读取来源文件元数据",
                        details={"error": type(exc).__name__},
                    )
                )
                continue
            is_reparse = bool(getattr(info, "st_file_attributes", 0) & REPARSE_POINT)
            if stat.S_ISLNK(info.st_mode) or is_reparse:
                bundle_issues.append(
                    SourceIssue(
                        code="source_link_rejected",
                        path=relative,
                        message="来源链接或 reparse point 已拒绝",
                    )
                )
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            regular_count += 1
            if regular_count > self.limits.max_files:
                bundle_issues.append(
                    SourceIssue(
                        code="source_file_count_exceeded",
                        message="来源文件数量超过安全限制",
                        details={"limit": self.limits.max_files},
                    )
                )
                break
            folded = relative.casefold()
            if (
                not relative
                or relative.startswith("/")
                or ".." in Path(relative).parts
                or any(ord(character) < 32 for character in relative)
                or len(relative.encode("utf-8")) > self.limits.max_path_bytes
                or folded in seen_paths
            ):
                bundle_issues.append(
                    SourceIssue(
                        code="source_path_rejected",
                        path=relative,
                        message="来源路径不符合安全约束",
                    )
                )
                continue
            seen_paths.add(folded)
            document, consumed = self._read_document(
                candidate, relative, hash_remaining, parsed_remaining
            )
            hash_remaining -= consumed
            if document.text is not None:
                parsed_remaining -= len(document.text)
            documents.append(document)
        completeness = self._bundle_completeness(documents, bundle_issues)
        manifest_payload = self._hash_payload(documents, bundle_issues, completeness, self.limits)
        bundle_hash = _canonical_hash(manifest_payload)
        bundle = SourceBundle(
            parser_version=PARSER_VERSION,
            limits=self.limits,
            documents=tuple(documents),
            issues=tuple(bundle_issues),
            completeness=completeness,
            bundle_hash=bundle_hash,
        )
        persisted = bundle.model_copy(
            update={
                "documents": tuple(
                    document.model_copy(update={"text": None}) for document in bundle.documents
                )
            }
        )
        return self._commit_source_bundle(run_root, manifest_path, bundle, persisted)

    def _commit_source_bundle(
        self,
        run_root: Path,
        manifest_path: Path,
        bundle: SourceBundle,
        persisted: SourceBundle,
    ) -> SourceBundle:
        snapshot_root = run_root / "source-snapshot"
        staging = Path(tempfile.mkdtemp(prefix=".source-bundle.", suffix=".staging", dir=run_root))
        staging_snapshot = staging / "source-snapshot"
        staging_snapshot.mkdir()
        published_snapshot = False
        try:
            for index, document in enumerate(bundle.documents):
                if document.text is not None:
                    atomic_text(staging_snapshot / f"{index:04}.txt", document.text)
            atomic_json(staging / "source-bundle.json", persisted.model_dump(mode="json"))
            self._sync_directory(staging_snapshot)
            self._sync_directory(staging)
            if snapshot_root.exists():
                if snapshot_root.is_symlink() or not snapshot_root.is_dir():
                    raise ValueError("uncommitted source snapshot path is invalid")
                shutil.rmtree(snapshot_root)
            os.rename(staging_snapshot, snapshot_root)
            published_snapshot = True
            self._sync_directory(run_root)
            atomic_json(manifest_path, persisted.model_dump(mode="json"))
            self._sync_directory(run_root)
            return bundle
        except Exception:
            if published_snapshot and not manifest_path.exists() and snapshot_root.is_dir():
                shutil.rmtree(snapshot_root)
                self._sync_directory(run_root)
            raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    @staticmethod
    def _sync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _scan_source_tree(self, source_root: Path) -> tuple[list[Path], list[SourceIssue]]:
        candidates: list[Path] = []
        issues: list[SourceIssue] = []
        try:
            root_info = source_root.lstat()
        except OSError as exc:
            return [], [
                SourceIssue(
                    code="source_read_failed",
                    path="sources",
                    message="无法读取来源根目录",
                    details={"error": type(exc).__name__},
                )
            ]
        root_reparse = bool(getattr(root_info, "st_file_attributes", 0) & REPARSE_POINT)
        if stat.S_ISLNK(root_info.st_mode) or root_reparse or not stat.S_ISDIR(root_info.st_mode):
            return [], [
                SourceIssue(
                    code="source_link_rejected",
                    path="sources",
                    message="来源根目录不是受信任的真实目录",
                )
            ]
        pending = [source_root]
        scanned = 0
        max_entries = self.limits.max_files * 16
        while pending:
            directory = pending.pop()
            try:
                directory_info = directory.lstat()
                directory_reparse = bool(
                    getattr(directory_info, "st_file_attributes", 0) & REPARSE_POINT
                )
                if stat.S_ISLNK(directory_info.st_mode) or directory_reparse:
                    issues.append(
                        SourceIssue(
                            code="source_link_rejected",
                            path=directory.relative_to(source_root.parent).as_posix(),
                            message="来源子目录链接或 reparse point 已拒绝",
                        )
                    )
                    continue
                with os.scandir(directory) as scan:
                    entries = sorted(
                        scan,
                        key=lambda item: unicodedata.normalize("NFC", item.name).casefold(),
                    )
            except OSError as exc:
                issues.append(
                    SourceIssue(
                        code="source_read_failed",
                        path=directory.relative_to(source_root.parent).as_posix(),
                        message="无法枚举来源目录",
                        details={"error": type(exc).__name__},
                    )
                )
                continue
            for entry in entries:
                scanned += 1
                if scanned > max_entries:
                    issues.append(
                        SourceIssue(
                            code="source_scan_limit_exceeded",
                            message="来源目录条目数量超过安全扫描限制",
                            details={"limit": max_entries},
                        )
                    )
                    return sorted(candidates, key=lambda item: item.as_posix().casefold()), issues
                path = Path(entry.path)
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    candidates.append(path)
                    continue
                is_reparse = bool(getattr(info, "st_file_attributes", 0) & REPARSE_POINT)
                if stat.S_ISLNK(info.st_mode) or is_reparse:
                    candidates.append(path)
                elif stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                else:
                    candidates.append(path)
        return sorted(candidates, key=lambda item: item.as_posix().casefold()), issues

    def load_source_bundle(self, workspace: str, run_id: str) -> SourceBundle:
        run_root = self.workspaces.require_workspace(workspace) / "runs" / run_id
        path = run_root / "source-bundle.json"
        if not path.is_file():
            raise FileNotFoundError(f"run 缺少 source bundle: {run_id}")
        bundle = SourceBundle.model_validate_json(path.read_text(encoding="utf-8"))
        snapshot_root = run_root / "source-snapshot"
        expected_snapshots = {
            f"{index:04}.txt": document
            for index, document in enumerate(bundle.documents)
            if document.parsed_sha256 is not None
            or document.completeness in {SourceCompleteness.COMPLETE, SourceCompleteness.PARTIAL}
        }
        actual_snapshots: set[str] = set()
        if snapshot_root.exists():
            if snapshot_root.is_symlink() or not snapshot_root.is_dir():
                raise ValueError("source snapshot 目录无效: source-snapshot")
            actual_snapshots = {entry.name for entry in snapshot_root.iterdir()}
        unexpected = sorted(actual_snapshots - set(expected_snapshots))
        if unexpected:
            raise ValueError(f"source snapshot 存在未声明文件: {unexpected[0]}")
        documents: list[SourceDocument] = []
        for index, document in enumerate(bundle.documents):
            name = f"{index:04}.txt"
            snapshot = snapshot_root / name
            requires_snapshot = name in expected_snapshots
            if requires_snapshot and name not in actual_snapshots:
                raise ValueError(f"source snapshot 缺失: {document.path}")
            if requires_snapshot and (snapshot.is_symlink() or not snapshot.is_file()):
                raise ValueError(f"source snapshot 文件无效: {document.path}")
            text = snapshot.read_bytes().decode("utf-8") if requires_snapshot else None
            if text is not None and _sha256(text.encode("utf-8")) != document.parsed_sha256:
                raise ValueError(f"source snapshot hash 校验失败: {document.path}")
            documents.append(document.model_copy(update={"text": text}))
        loaded = bundle.model_copy(update={"documents": tuple(documents)})
        expected = _canonical_hash(
            self._hash_payload(
                list(loaded.documents),
                list(loaded.issues),
                loaded.completeness,
                loaded.limits,
                loaded.parser_version,
            )
        )
        if expected != loaded.bundle_hash:
            raise ValueError("source bundle hash 校验失败")
        return loaded

    def _read_document(
        self, path: Path, relative: str, hash_remaining: int, parsed_remaining: int
    ) -> tuple[SourceDocument, int]:
        issues: list[SourceIssue] = []
        try:
            before = path.stat()
            size = before.st_size
            if size > self.limits.max_hash_bytes or size > hash_remaining:
                return (
                    SourceDocument(
                        path=relative,
                        byte_size=size,
                        completeness=SourceCompleteness.UNAVAILABLE,
                        issues=(
                            SourceIssue(
                                code="source_unhashed_due_to_limit",
                                path=relative,
                                message="来源文件超过安全读取或总哈希预算",
                                details={
                                    "hash_limit": self.limits.max_hash_bytes,
                                    "remaining_total_hash": max(hash_remaining, 0),
                                    "size": size,
                                },
                            ),
                        ),
                    ),
                    0,
                )
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode):
                    raise OSError("source is no longer a regular file")
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise OSError("source changed before it was opened")
                hasher = hashlib.sha256()
                chunks: list[bytes] | None = [] if size <= self.limits.max_parse_bytes else None
                bytes_read = 0
                with os.fdopen(descriptor, "rb", closefd=False) as handle:
                    while chunk := handle.read(HASH_CHUNK_BYTES):
                        bytes_read += len(chunk)
                        hasher.update(chunk)
                        if chunks is not None:
                            chunks.append(chunk)
                after = os.fstat(descriptor)
                if bytes_read != size or (after.st_size, after.st_mtime_ns) != (
                    before.st_size,
                    before.st_mtime_ns,
                ):
                    raise OSError("source changed while being read")
            finally:
                os.close(descriptor)
        except OSError as exc:
            return (
                SourceDocument(
                    path=relative,
                    completeness=SourceCompleteness.UNAVAILABLE,
                    issues=(
                        SourceIssue(
                            code="source_read_failed",
                            path=relative,
                            message="来源文件读取失败",
                            details={"error": type(exc).__name__},
                        ),
                    ),
                ),
                0,
            )
        raw_hash = f"sha256:{hasher.hexdigest()}"
        if chunks is None:
            return (
                SourceDocument(
                    path=relative,
                    raw_sha256=raw_hash,
                    byte_size=size,
                    completeness=SourceCompleteness.UNAVAILABLE,
                    issues=(
                        SourceIssue(
                            code="source_unparsed_due_to_limit",
                            path=relative,
                            message="来源文件已完整计算哈希，但超过解析预算",
                            details={"parse_limit": self.limits.max_parse_bytes, "size": size},
                        ),
                    ),
                ),
                size,
            )
        data = b"".join(chunks)
        try:
            decoded = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            return (
                SourceDocument(
                    path=relative,
                    raw_sha256=raw_hash,
                    byte_size=len(data),
                    completeness=SourceCompleteness.UNAVAILABLE,
                    issues=(
                        SourceIssue(
                            code="source_non_utf8",
                            path=relative,
                            message="来源文件不是有效 UTF-8",
                            details={"start": exc.start},
                        ),
                    ),
                ),
                len(data),
            )
        truncated = len(decoded) > max(parsed_remaining, 0)
        text = decoded[: max(parsed_remaining, 0)]
        if truncated:
            issues.append(
                SourceIssue(
                    code="source_truncated",
                    path=relative,
                    message="来源文本超过解析字符预算，已截断",
                    details={"parsed_characters": len(text), "original_characters": len(decoded)},
                )
            )
        issues.extend(_critical_structure_issues(relative, text, truncated))
        completeness = SourceCompleteness.PARTIAL if truncated else SourceCompleteness.COMPLETE
        return (
            SourceDocument(
                path=relative,
                raw_sha256=raw_hash,
                parsed_sha256=_sha256(text.encode("utf-8")),
                byte_size=len(data),
                text=text,
                completeness=completeness,
                truncated=truncated,
                issues=tuple(issues),
            ),
            len(data),
        )

    @staticmethod
    def _bundle_completeness(
        documents: list[SourceDocument], issues: list[SourceIssue]
    ) -> SourceCompleteness:
        if not documents:
            return SourceCompleteness.UNAVAILABLE if issues else SourceCompleteness.EMPTY
        all_complete = all(item.completeness == SourceCompleteness.COMPLETE for item in documents)
        if all_complete and not issues:
            return SourceCompleteness.COMPLETE
        if any(item.text is not None for item in documents):
            return SourceCompleteness.PARTIAL
        return SourceCompleteness.UNAVAILABLE

    def _hash_payload(
        self,
        documents: list[SourceDocument],
        issues: list[SourceIssue],
        completeness: SourceCompleteness,
        limits: SourceIngestionLimits,
        parser_version: str = PARSER_VERSION,
    ) -> dict[str, Any]:
        if parser_version == "2.0.0" and limits.max_file_bytes and limits.max_total_bytes:
            limits_payload = {
                "max_files": limits.max_files,
                "max_path_bytes": limits.max_path_bytes,
                "max_file_bytes": limits.max_file_bytes,
                "max_total_bytes": limits.max_total_bytes,
                "max_parsed_characters": limits.max_parsed_characters,
            }
        else:
            limits_payload = limits.model_dump(mode="json", exclude_none=True)
        return {
            "schema": "agentic-qa.harness.source-bundle-hash.v2",
            "parser_version": parser_version,
            "limits": limits_payload,
            "completeness": completeness.value,
            "documents": [
                {
                    "path": item.path,
                    "raw_sha256": item.raw_sha256,
                    "parsed_sha256": item.parsed_sha256,
                    "byte_size": item.byte_size,
                    "completeness": item.completeness.value,
                    "truncated": item.truncated,
                    "issues": [_issue_payload(issue) for issue in item.issues],
                }
                for item in documents
            ],
            "issues": [_issue_payload(issue) for issue in issues],
        }
