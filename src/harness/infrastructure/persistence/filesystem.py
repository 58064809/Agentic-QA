from __future__ import annotations

import base64
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from harness.application.quality import QualityReport
from harness.application.source import SourceBundle, SourceIngestionLimits
from harness.domain.models import (
    ApprovedArtifactVersion,
    ArtifactCandidate,
    ArtifactDiffResult,
    ExecutionEnvironmentPolicy,
    ExecutionProfile,
    GetArtifactDiffQuery,
    HarnessEvent,
    RunSnapshot,
)
from harness.infrastructure.persistence.artifact_repository import (
    ArtifactReviewFilesystemRepository,
    _exclusive_file_lock,
)
from harness.infrastructure.persistence.common import atomic_bytes, atomic_json
from harness.infrastructure.persistence.run_repository import RunEventFilesystemRepository
from harness.infrastructure.persistence.source_bundle_repository import (
    SourceBundleFilesystemRepository,
)
from harness.infrastructure.persistence.workspace_repository import WorkspaceFilesystemRepository


class FilesystemStore:
    """组合三个独立文件仓储，供基础设施工作流统一注入。"""

    def __init__(
        self,
        repo_root: Path | str,
        *,
        source_limits: SourceIngestionLimits | None = None,
    ) -> None:
        self.workspaces = WorkspaceFilesystemRepository(repo_root)
        self.runs = RunEventFilesystemRepository(self.workspaces)
        self.artifacts = ArtifactReviewFilesystemRepository(self.workspaces)
        self.sources = SourceBundleFilesystemRepository(self.workspaces, source_limits)
        self.repo_root = self.workspaces.repo_root
        self.root = self.workspaces.root

    def workspace_path(self, workspace: str) -> Path:
        return self.workspaces.workspace_path(workspace)

    def init_workspace(self, workspace: str, *, quality_policies: list[str]) -> Path:
        return self.workspaces.init_workspace(workspace, quality_policies=quality_policies)

    def require_workspace(self, workspace: str) -> Path:
        return self.workspaces.require_workspace(workspace)

    def workspace_config(self, workspace: str) -> dict[str, Any]:
        return self.workspaces.workspace_config(workspace)

    def validate_execution_profile(
        self, workspace: str, profile: ExecutionProfile
    ) -> ExecutionEnvironmentPolicy | None:
        return self.workspaces.validate_execution_profile(workspace, profile)

    def create_source_bundle(self, workspace: str, run_id: str) -> SourceBundle:
        return self.sources.create_source_bundle(workspace, run_id)

    def load_source_bundle(self, workspace: str, run_id: str) -> SourceBundle:
        return self.sources.load_source_bundle(workspace, run_id)

    def create_run(self, snapshot: RunSnapshot) -> None:
        self.runs.create_run(snapshot)

    def save_snapshot(self, snapshot: RunSnapshot) -> None:
        self.runs.save_snapshot(snapshot)

    def next_event_sequence(self, workspace: str, run_id: str) -> int:
        return self.runs.next_event_sequence(workspace, run_id)

    def append_event(self, workspace: str, event: HarnessEvent) -> None:
        self.runs.append_event(workspace, event)

    def has_assessment_event(self, workspace: str, run_id: str, assessment_key: str) -> bool:
        return self.runs.has_assessment_event(workspace, run_id, assessment_key)

    def write_tool_record(
        self, workspace: str, run_id: str, name: str, payload: dict[str, Any]
    ) -> Path:
        return self.runs.write_tool_record(workspace, run_id, name, payload)

    def tool_records(self, workspace: str, run_id: str) -> list[dict[str, Any]]:
        return self.runs.tool_records(workspace, run_id)

    def load_snapshot(self, workspace: str, run_id: str) -> RunSnapshot:
        snapshot = self.runs.load_snapshot(workspace, run_id)
        self._recover_publication(snapshot)
        return self.runs.load_snapshot(workspace, run_id)

    def commit_candidate(self, **kwargs: Any) -> tuple[ArtifactCandidate, bool]:
        return self.artifacts.commit_candidate(**kwargs)

    def load_candidate(self, **kwargs: Any) -> ArtifactCandidate | None:
        return self.artifacts.load_candidate(**kwargs)

    def load_quality_report(self, candidate: ArtifactCandidate) -> QualityReport:
        return self.artifacts.load_quality_report(candidate)

    def get_artifact_diff(self, query: GetArtifactDiffQuery) -> ArtifactDiffResult:
        return self.artifacts.get_artifact_diff(query)

    def write_review(self, snapshot: RunSnapshot, artifact: str, payload: dict[str, Any]) -> None:
        self.artifacts.write_review(snapshot, artifact, payload)

    def promote_many(
        self, snapshot: RunSnapshot, versions: list[ApprovedArtifactVersion]
    ) -> dict[str, str]:
        return self.artifacts.promote_many(snapshot, versions)

    def publish_review(
        self,
        snapshot: RunSnapshot,
        versions: list[ApprovedArtifactVersion],
        review_records: dict[str, dict[str, object]],
    ) -> None:
        review_root = self.require_workspace(snapshot.workspace_id) / "reviews" / snapshot.run_id
        journal_path = review_root / "publication-intent.json"
        lock_path = review_root / ".publication.lock"
        with _exclusive_file_lock(lock_path):
            self._recover_publication(snapshot, locked=True)
            publication_id = self._publication_id(snapshot, versions)
            if journal_path.is_file():
                prior = json.loads(journal_path.read_text(encoding="utf-8"))
                if (
                    prior.get("publication_id") == publication_id
                    and prior.get("status") == "committed"
                ):
                    return
                archive = review_root / "publication-history" / f"{prior['publication_id']}.json"
                archive.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(journal_path, archive)
            self.artifacts.verify_many(snapshot, versions)
            paths = self._publication_paths(snapshot, versions, review_records)
            journal = {
                "schema_version": "agentic-qa.harness.publication-intent.v2",
                "publication_id": publication_id,
                "status": "preparing",
                "workspace_id": snapshot.workspace_id,
                "run_id": snapshot.run_id,
                "versions": [item.model_dump(mode="json") for item in versions],
                "review_records": review_records,
                "target_snapshot": snapshot.model_dump(mode="json"),
                "backups": self._capture_paths(paths),
            }
            atomic_json(journal_path, journal)
            self._complete_publication(journal_path, journal)

    def _recover_publication(self, snapshot: RunSnapshot, *, locked: bool = False) -> None:
        review_root = self.require_workspace(snapshot.workspace_id) / "reviews" / snapshot.run_id
        journal_path = review_root / "publication-intent.json"
        if not journal_path.is_file():
            return
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if journal.get("status") != "preparing":
            return
        if not locked:
            with _exclusive_file_lock(review_root / ".publication.lock"):
                return self._recover_publication(snapshot, locked=True)
        try:
            self._complete_publication(journal_path, journal)
        except (ValueError, PermissionError, FileNotFoundError):
            self._restore_paths(journal["backups"])
            journal["status"] = "rolled_back"
            atomic_json(journal_path, journal)

    def _complete_publication(self, journal_path: Path, journal: dict[str, Any]) -> None:
        snapshot = RunSnapshot.model_validate(journal["target_snapshot"])
        versions = [ApprovedArtifactVersion.model_validate(item) for item in journal["versions"]]
        self.artifacts.verify_many(snapshot, versions)
        self.artifacts.promote_many(snapshot, versions)
        for artifact, payload in journal["review_records"].items():
            self.artifacts.write_review(snapshot, artifact, payload)
        self.runs.save_snapshot(snapshot)
        publication_id = journal["publication_id"]
        if not self.runs.has_publication_event(
            snapshot.workspace_id, snapshot.run_id, publication_id
        ):
            first_record = next(iter(journal["review_records"].values()))
            decision = first_record.get("decision") or {}
            self.runs.append_event(
                snapshot.workspace_id,
                HarnessEvent(
                    sequence=self.runs.next_event_sequence(snapshot.workspace_id, snapshot.run_id),
                    run_id=snapshot.run_id,
                    type="review_applied",
                    data={
                        "decision": "approve",
                        "reviewed_by": decision.get("reviewed_by"),
                        "reason": decision.get("reason"),
                        "status": snapshot.status,
                        "publication_id": publication_id,
                    },
                ),
            )
        journal["status"] = "committed"
        atomic_json(journal_path, journal)

    def _publication_paths(
        self,
        snapshot: RunSnapshot,
        versions: list[ApprovedArtifactVersion],
        records: dict[str, dict[str, object]],
    ) -> list[Path]:
        workspace = self.require_workspace(snapshot.workspace_id)
        paths = [workspace / "runs" / snapshot.run_id / "state.json"]
        for version in versions:
            suffix = Path(version.path).suffix
            published = workspace / "published" / version.artifact
            paths.extend(
                [
                    published / f"current{suffix}",
                    published / "history" / f"{snapshot.run_id}{suffix}",
                    published / "history" / "index.yml",
                ]
            )
        paths.extend(
            workspace / "reviews" / snapshot.run_id / f"{artifact}.review.json"
            for artifact in records
        )
        return paths

    def _capture_paths(self, paths: list[Path]) -> dict[str, str | None]:
        return {
            path.relative_to(self.repo_root).as_posix(): (
                base64.b64encode(path.read_bytes()).decode("ascii") if path.is_file() else None
            )
            for path in paths
        }

    def _restore_paths(self, backups: dict[str, str | None]) -> None:
        for relative, encoded in backups.items():
            path = self.repo_root / relative
            if encoded is None:
                if path.is_file():
                    path.unlink()
            else:
                atomic_bytes(path, base64.b64decode(encoded))

    @staticmethod
    def _publication_id(snapshot: RunSnapshot, versions: list[ApprovedArtifactVersion]) -> str:
        value = json.dumps(
            {
                "workspace_id": snapshot.workspace_id,
                "run_id": snapshot.run_id,
                "versions": [item.model_dump(mode="json") for item in versions],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return f"sha256:{hashlib.sha256(value).hexdigest()}"
