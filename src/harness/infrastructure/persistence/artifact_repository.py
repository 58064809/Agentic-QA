from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from harness.domain.models import ArtifactCandidate, RunSnapshot
from harness.infrastructure.persistence.common import atomic_bytes, atomic_json, atomic_text
from harness.infrastructure.persistence.workspace_repository import WorkspaceFilesystemRepository

UTC = timezone.utc
ARTIFACT_FILENAMES = {
    "requirement_analysis": "requirement-analysis.md",
    "testcases": "testcases.md",
    "api_test_draft": "api-test-draft.md",
    "ui_test_draft": "ui-test-draft.md",
    "api_discovery_report": "api-discovery-report.md",
    "qa_report": "qa-report.md",
    "execution_report": "execution-report.md",
    "failure_analysis": "failure-analysis.md",
    "bug_draft": "bug-draft.md",
}


class ArtifactReviewFilesystemRepository:
    def __init__(self, workspaces: WorkspaceFilesystemRepository) -> None:
        self.workspaces = workspaces
        self.repo_root = workspaces.repo_root

    def write_candidate(
        self,
        *,
        workspace: str,
        run_id: str,
        artifact: str,
        content: str,
        partial: bool = False,
        evidence: list[str] | None = None,
    ) -> ArtifactCandidate:
        target = (
            self.workspaces.require_workspace(workspace)
            / "candidates"
            / run_id
            / ARTIFACT_FILENAMES[artifact]
        )
        if target.exists():
            raise FileExistsError(f"候选产物已存在，不允许覆盖: {target}")
        atomic_text(target, content)
        return self._candidate(target, artifact, partial, evidence)

    def ensure_candidate(
        self,
        *,
        workspace: str,
        run_id: str,
        artifact: str,
        content: str,
        partial: bool = False,
        evidence: list[str] | None = None,
    ) -> ArtifactCandidate:
        target = (
            self.workspaces.require_workspace(workspace)
            / "candidates"
            / run_id
            / ARTIFACT_FILENAMES[artifact]
        )
        if target.exists():
            if target.read_text(encoding="utf-8") != content:
                raise FileExistsError(f"候选产物已存在且内容不同，不允许覆盖: {target}")
            return self._candidate(target, artifact, partial, evidence)
        return self.write_candidate(
            workspace=workspace,
            run_id=run_id,
            artifact=artifact,
            content=content,
            partial=partial,
            evidence=evidence,
        )

    def load_candidate(
        self,
        *,
        workspace: str,
        run_id: str,
        artifact: str,
        partial: bool = False,
        evidence: list[str] | None = None,
    ) -> ArtifactCandidate | None:
        target = (
            self.workspaces.require_workspace(workspace)
            / "candidates"
            / run_id
            / ARTIFACT_FILENAMES[artifact]
        )
        if not target.is_file():
            return None
        return self._candidate(target, artifact, partial, evidence)

    def write_review(
        self,
        snapshot: RunSnapshot,
        artifact: str,
        payload: dict[str, Any],
    ) -> None:
        path = (
            self.workspaces.require_workspace(snapshot.workspace_id)
            / "reviews"
            / snapshot.run_id
            / f"{artifact}.review.json"
        )
        atomic_json(path, payload)

    def promote(self, snapshot: RunSnapshot, artifact: str) -> str:
        candidate = next((item for item in snapshot.candidates if item.artifact == artifact), None)
        if candidate is None:
            raise KeyError(f"run 中没有候选产物: {artifact}")
        if snapshot.review_status.get(artifact) != "approved":
            raise PermissionError(f"只有 approved 候选可以 promote: {artifact}")
        workspace = self.workspaces.require_workspace(snapshot.workspace_id)
        source = (self.repo_root / candidate.path).resolve()
        candidate_root = (workspace / "candidates" / snapshot.run_id).resolve()
        if source.parent != candidate_root or not source.is_file():
            raise ValueError("候选路径越界或不存在")
        published = workspace / "published" / artifact
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
                    "path": history_target.relative_to(workspace).as_posix(),
                    "published_at": datetime.now(tz=UTC).isoformat(),
                }
            )
        index["versions"] = versions
        atomic_text(index_path, yaml.safe_dump(index, allow_unicode=True, sort_keys=False))
        return current.relative_to(self.repo_root).as_posix()

    def promote_many(self, snapshot: RunSnapshot, artifacts: list[str]) -> dict[str, str]:
        tracked: dict[Path, bytes | None] = {}
        workspace = self.workspaces.require_workspace(snapshot.workspace_id)
        for artifact in artifacts:
            candidate = next(item for item in snapshot.candidates if item.artifact == artifact)
            source = (self.repo_root / candidate.path).resolve()
            published = workspace / "published" / artifact
            for path in (
                published / f"current{source.suffix}",
                published / "history" / f"{snapshot.run_id}{source.suffix}",
                published / "history" / "index.yml",
            ):
                if path not in tracked:
                    tracked[path] = path.read_bytes() if path.is_file() else None
        promoted: dict[str, str] = {}
        try:
            for artifact in artifacts:
                promoted[artifact] = self.promote(snapshot, artifact)
        except Exception:
            for path, content in tracked.items():
                if content is None:
                    if path.is_file():
                        path.unlink()
                else:
                    atomic_bytes(path, content)
            raise
        return promoted

    def _candidate(
        self,
        target: Path,
        artifact: str,
        partial: bool,
        evidence: list[str] | None,
    ) -> ArtifactCandidate:
        return ArtifactCandidate(
            artifact=artifact,
            path=target.relative_to(self.repo_root).as_posix(),
            status="partial" if partial else "needs_human_review",
            quality_passed=not partial,
            evidence=evidence or [],
        )
