from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from harness.application.quality import ArtifactVariant, CandidateAssessment, QualityReport
from harness.domain.models import (
    ApprovedArtifactVersion,
    ArtifactCandidate,
    ArtifactVersion,
    RunSnapshot,
)
from harness.infrastructure.persistence.common import atomic_bytes, atomic_json, atomic_text
from harness.infrastructure.persistence.workspace_repository import WorkspaceFilesystemRepository

UTC = timezone.utc
ARTIFACT_EXTENSIONS = {
    "requirement_analysis": ".md",
    "testcases": ".md",
    "api_test_draft": ".md",
    "ui_test_draft": ".md",
    "api_discovery_report": ".md",
    "qa_report": ".md",
    "execution_report": ".md",
    "failure_analysis": ".md",
    "bug_draft": ".md",
}


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


@contextmanager
def _exclusive_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        handle.seek(0)
        if handle.tell() == 0 and path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _write_fsynced(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


class ArtifactReviewFilesystemRepository:
    def __init__(self, workspaces: WorkspaceFilesystemRepository) -> None:
        self.workspaces = workspaces
        self.repo_root = workspaces.repo_root

    def commit_candidate(
        self,
        *,
        workspace: str,
        run_id: str,
        artifact: str,
        assessment: CandidateAssessment,
        partial: bool = False,
        evidence: list[str] | None = None,
    ) -> tuple[ArtifactCandidate, bool]:
        workspace_root = self.workspaces.require_workspace(workspace)
        run_root = workspace_root / "candidates" / run_id
        final = run_root / artifact
        lock = run_root / ".locks" / f"{artifact}.lock"
        extension = ARTIFACT_EXTENSIONS[artifact]
        with _exclusive_file_lock(lock):
            if final.exists():
                return self._load_committed(final, artifact, partial, evidence, assessment)
            staging_root = run_root / ".staging"
            staging_root.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f"{artifact}.", dir=staging_root))
            try:
                files: dict[str, bytes] = {
                    f"raw{extension}": assessment.raw_content.encode("utf-8"),
                    "quality-report.json": _json_bytes(assessment.report.model_dump(mode="json")),
                }
                if assessment.normalized_content is not None:
                    files[f"normalized{extension}"] = assessment.normalized_content.encode("utf-8")
                if assessment.normalization_patch:
                    files["normalization.patch"] = assessment.normalization_patch.encode("utf-8")
                if assessment.remediation_patch:
                    files["remediation.patch"] = assessment.remediation_patch.encode("utf-8")
                hashes: dict[str, str] = {}
                for name, content in files.items():
                    _write_fsynced(staging / name, content)
                    hashes[name] = _sha256_bytes(content)
                manifest = {
                    "schema_version": "agentic-qa.harness.candidate-manifest.v2",
                    "artifact": artifact,
                    "assessment_key": assessment.report.assessment_key,
                    "source_bundle_hash": assessment.report.source_bundle_hash,
                    "files": hashes,
                }
                _write_fsynced(staging / "manifest.json", _json_bytes(manifest))
                self._sync_directory(staging)
                if final.exists():
                    return self._load_committed(final, artifact, partial, evidence, assessment)
                os.rename(staging, final)
                self._sync_directory(run_root)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
            candidate = self._candidate(final, artifact, partial, evidence)
            return candidate, True

    def load_candidate(
        self,
        *,
        workspace: str,
        run_id: str,
        artifact: str,
        partial: bool = False,
        evidence: list[str] | None = None,
    ) -> ArtifactCandidate | None:
        final = self.workspaces.require_workspace(workspace) / "candidates" / run_id / artifact
        if not (final / "manifest.json").is_file():
            return None
        return self._candidate(final, artifact, partial, evidence)

    def load_quality_report(self, candidate: ArtifactCandidate) -> QualityReport:
        if not candidate.quality_report_path:
            raise PermissionError("candidate 缺少质量报告，不能审核或发布")
        path = (self.repo_root / candidate.quality_report_path).resolve()
        report = QualityReport.model_validate_json(path.read_text(encoding="utf-8"))
        if _sha256_bytes(path.read_bytes()) != candidate.quality_report_sha256:
            raise ValueError("quality report hash 不匹配")
        return report

    def write_review(self, snapshot: RunSnapshot, artifact: str, payload: dict[str, Any]) -> None:
        path = (
            self.workspaces.require_workspace(snapshot.workspace_id)
            / "reviews"
            / snapshot.run_id
            / f"{artifact}.review.json"
        )
        atomic_json(path, payload)

    def promote_many(
        self,
        snapshot: RunSnapshot,
        versions: list[ApprovedArtifactVersion],
    ) -> dict[str, str]:
        tracked: dict[Path, bytes | None] = {}
        workspace = self.workspaces.require_workspace(snapshot.workspace_id)
        for version in versions:
            source = self._verified_approved_source(snapshot, version)
            published = workspace / "published" / version.artifact
            for path in (
                published / f"current{source.suffix}",
                published / "history" / f"{snapshot.run_id}{source.suffix}",
                published / "history" / "index.yml",
            ):
                tracked[path] = path.read_bytes() if path.is_file() else None
        promoted: dict[str, str] = {}
        try:
            for version in versions:
                promoted[version.artifact] = self._promote(snapshot, version)
        except Exception:
            for path, content in tracked.items():
                if content is None:
                    if path.is_file():
                        path.unlink()
                else:
                    atomic_bytes(path, content)
            raise
        return promoted

    def _promote(self, snapshot: RunSnapshot, version: ApprovedArtifactVersion) -> str:
        source = self._verified_approved_source(snapshot, version)
        workspace = self.workspaces.require_workspace(snapshot.workspace_id)
        published = workspace / "published" / version.artifact
        history = published / "history"
        history.mkdir(parents=True, exist_ok=True)
        current = published / f"current{source.suffix}"
        history_target = history / f"{snapshot.run_id}{source.suffix}"
        if not history_target.exists():
            shutil.copyfile(source, history_target)
        temporary = published / f".current.{snapshot.run_id}.tmp"
        shutil.copyfile(source, temporary)
        os.replace(temporary, current)
        index_path = history / "index.yml"
        index: dict[str, Any] = {
            "schema_version": "agentic-qa.harness.history.v2",
            "versions": [],
        }
        if index_path.exists():
            loaded = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                index = loaded
        versions = list(index.get("versions") or [])
        if not any(item.get("run_id") == snapshot.run_id for item in versions):
            versions.append(
                {
                    "run_id": snapshot.run_id,
                    "variant": version.variant.value,
                    "content_sha256": version.content_sha256,
                    "assessment_key": version.assessment_key,
                    "path": history_target.relative_to(workspace).as_posix(),
                    "published_at": datetime.now(tz=UTC).isoformat(),
                }
            )
        index["versions"] = versions
        atomic_text(index_path, yaml.safe_dump(index, allow_unicode=True, sort_keys=False))
        return current.relative_to(self.repo_root).as_posix()

    def _verified_approved_source(
        self, snapshot: RunSnapshot, version: ApprovedArtifactVersion
    ) -> Path:
        candidate = next(
            (item for item in snapshot.candidates if item.artifact == version.artifact), None
        )
        if candidate is None:
            raise PermissionError(f"artifact 不在当前候选中: {version.artifact}")
        if candidate.assessment_key != version.assessment_key:
            raise ValueError("approved assessment key 与 candidate 不匹配")
        if candidate.quality_report_sha256 != version.quality_report_sha256:
            raise ValueError("approved quality report 与 candidate 不匹配")
        if not candidate.quality_report_path:
            raise ValueError("candidate 缺少质量报告路径")
        report_path = (self.repo_root / candidate.quality_report_path).resolve()
        expected_report_root = (
            self.workspaces.require_workspace(snapshot.workspace_id)
            / "candidates"
            / snapshot.run_id
            / version.artifact
        ).resolve()
        if (
            report_path.parent != expected_report_root
            or not report_path.is_file()
            or _sha256_bytes(report_path.read_bytes()) != version.quality_report_sha256
        ):
            raise ValueError("approved quality report 内容 hash 已变化")
        expected = next(
            (
                item
                for item in candidate.versions
                if item.variant == version.variant
                and item.content_sha256 == version.content_sha256
                and item.path == version.path
            ),
            None,
        )
        if expected is None:
            raise ValueError("approved artifact version 与 candidate manifest 不匹配")
        source = (self.repo_root / version.path).resolve()
        candidate_root = (
            self.workspaces.require_workspace(snapshot.workspace_id)
            / "candidates"
            / snapshot.run_id
            / version.artifact
        ).resolve()
        if source.parent != candidate_root or not source.is_file():
            raise ValueError("candidate version 路径越界或不存在")
        if _sha256_bytes(source.read_bytes()) != version.content_sha256:
            raise ValueError("candidate version 内容 hash 已变化")
        return source

    def _load_committed(
        self,
        final: Path,
        artifact: str,
        partial: bool,
        evidence: list[str] | None,
        assessment: CandidateAssessment,
    ) -> tuple[ArtifactCandidate, bool]:
        manifest = self._validated_manifest(final)
        if manifest["assessment_key"] != assessment.report.assessment_key:
            raise FileExistsError("candidate 已存在且 assessment key 不同，不允许覆盖")
        return self._candidate(final, artifact, partial, evidence), False

    def _candidate(
        self,
        final: Path,
        artifact: str,
        partial: bool,
        evidence: list[str] | None,
    ) -> ArtifactCandidate:
        manifest = self._validated_manifest(final)
        if manifest.get("artifact") != artifact:
            raise ValueError("candidate manifest artifact 不匹配")
        extension = ARTIFACT_EXTENSIONS[artifact]
        versions = [
            ArtifactVersion(
                variant=ArtifactVariant.RAW,
                path=(final / f"raw{extension}").relative_to(self.repo_root).as_posix(),
                content_sha256=manifest["files"][f"raw{extension}"],
            )
        ]
        normalized_name = f"normalized{extension}"
        if normalized_name in manifest["files"]:
            versions.append(
                ArtifactVersion(
                    variant=ArtifactVariant.NORMALIZED,
                    path=(final / normalized_name).relative_to(self.repo_root).as_posix(),
                    content_sha256=manifest["files"][normalized_name],
                )
            )
        report_path = final / "quality-report.json"
        report = QualityReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        return ArtifactCandidate(
            artifact=artifact,
            path=versions[0].path,
            status="partial" if partial else "needs_human_review",
            evidence=evidence or [],
            versions=versions,
            assessment_key=manifest["assessment_key"],
            quality_report_path=report_path.relative_to(self.repo_root).as_posix(),
            quality_report_sha256=manifest["files"]["quality-report.json"],
            source_bundle_hash=manifest["source_bundle_hash"],
            policy_versions=report.policy_versions,
        )

    @staticmethod
    def _validated_manifest(final: Path) -> dict[str, Any]:
        manifest_path = final / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("candidate bundle 缺少 manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != "agentic-qa.harness.candidate-manifest.v2":
            raise ValueError("candidate manifest schema 不受支持")
        for name, expected in manifest.get("files", {}).items():
            path = (final / name).resolve()
            if path.parent != final.resolve() or not path.is_file():
                raise ValueError("candidate manifest 文件路径无效")
            if _sha256_bytes(path.read_bytes()) != expected:
                raise ValueError(f"candidate bundle 文件 hash 不匹配: {name}")
        return manifest

    @staticmethod
    def _sync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
