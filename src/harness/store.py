from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from harness.contracts import ArtifactCandidate, HarnessEvent, RunSnapshot

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
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


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _json(path: Path, payload: Any) -> None:
    _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


class WorkspaceStore:
    def __init__(self, repo_root: Path | str):
        self.repo_root = Path(repo_root).resolve()
        self.root = self.repo_root / "workspaces"

    def workspace_path(self, workspace: str) -> Path:
        if not SAFE_ID.fullmatch(workspace):
            raise ValueError("workspace 标识不安全")
        path = (self.root / workspace).resolve()
        if path.parent != self.root.resolve():
            raise ValueError("workspace 路径越界")
        return path

    def init_workspace(self, workspace: str) -> Path:
        path = self.workspace_path(workspace)
        if path.exists():
            raise FileExistsError(f"workspace 已存在: {workspace}")
        for relative in (
            "sources",
            "runs",
            "candidates",
            "reviews",
            "published",
            "memory",
        ):
            (path / relative).mkdir(parents=True, exist_ok=False)
        _atomic_text(
            path / "workspace.yml",
            yaml.safe_dump(
                {
                    "schema_version": "agentic-qa.harness.workspace.v1",
                    "id": workspace,
                    "created_at": datetime.now(tz=UTC).isoformat(),
                },
                allow_unicode=True,
                sort_keys=False,
            ),
        )
        return path

    def require_workspace(self, workspace: str) -> Path:
        path = self.workspace_path(workspace)
        if not (path / "workspace.yml").is_file():
            raise FileNotFoundError(
                f"workspace 不存在: {workspace}；先运行 agentic-qa workspace init {workspace}"
            )
        return path

    def create_run(self, snapshot: RunSnapshot) -> None:
        workspace = self.require_workspace(snapshot.workspace)
        run = workspace / "runs" / snapshot.run_id
        run.mkdir(parents=False, exist_ok=False)
        for relative in ("checkpoints", "tool-calls"):
            (run / relative).mkdir()
        (workspace / "candidates" / snapshot.run_id).mkdir()
        (workspace / "reviews" / snapshot.run_id).mkdir()
        _json(run / "task.json", snapshot.request.model_dump(mode="json"))
        self.save_snapshot(snapshot)

    def save_snapshot(self, snapshot: RunSnapshot) -> None:
        run = self.require_workspace(snapshot.workspace) / "runs" / snapshot.run_id
        snapshot.updated_at = datetime.now(tz=UTC)
        payload = snapshot.model_dump(mode="json")
        _json(run / "state.json", payload)
        if snapshot.plan is not None:
            _json(run / "plan.json", snapshot.plan.model_dump(mode="json"))
        checkpoint = run / "checkpoints" / f"{len(snapshot.completed_tasks):04d}.json"
        if not checkpoint.exists():
            _json(checkpoint, payload)

    def append_event(self, workspace: str, event: HarnessEvent) -> None:
        path = self.require_workspace(workspace) / "runs" / event.run_id / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(event.model_dump_json() + "\n")

    def load_snapshot(self, run_id: str) -> RunSnapshot:
        if not SAFE_ID.fullmatch(run_id):
            raise ValueError("run_id 不安全")
        matches = list(self.root.glob(f"*/runs/{run_id}/state.json"))
        if not matches:
            raise FileNotFoundError(f"run 不存在: {run_id}")
        if len(matches) > 1:
            raise RuntimeError(f"run_id 不唯一: {run_id}")
        return RunSnapshot.model_validate_json(matches[0].read_text(encoding="utf-8"))

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
        filename = ARTIFACT_FILENAMES[artifact]
        root = self.require_workspace(workspace)
        target = root / "candidates" / run_id / filename
        if target.exists():
            raise FileExistsError(f"候选产物已存在，不允许覆盖: {target}")
        _atomic_text(target, content)
        relative = target.relative_to(self.repo_root).as_posix()
        return ArtifactCandidate(
            artifact=artifact,
            path=relative,
            status="partial" if partial else "needs_human_review",
            quality_passed=not partial,
            evidence=evidence or [],
        )

    def write_review(self, snapshot: RunSnapshot, artifact: str, payload: dict[str, Any]) -> None:
        path = (
            self.require_workspace(snapshot.workspace)
            / "reviews"
            / snapshot.run_id
            / f"{artifact}.review.json"
        )
        _json(path, payload)

    def promote(self, snapshot: RunSnapshot, artifact: str) -> str:
        candidate = next((item for item in snapshot.candidates if item.artifact == artifact), None)
        if candidate is None:
            raise KeyError(f"run 中没有候选产物: {artifact}")
        if snapshot.review_status.get(artifact) != "approved":
            raise PermissionError(f"只有 approved 候选可以 promote: {artifact}")
        workspace = self.require_workspace(snapshot.workspace)
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
        index: dict[str, Any] = {"schema_version": "agentic-qa.harness.history.v1", "versions": []}
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
        _atomic_text(index_path, yaml.safe_dump(index, allow_unicode=True, sort_keys=False))
        return current.relative_to(self.repo_root).as_posix()

    def source_texts(self, workspace: str, limit: int = 100_000) -> list[tuple[str, str]]:
        root = self.require_workspace(workspace)
        result: list[tuple[str, str]] = []
        total = 0
        for path in sorted((root / "sources").rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            remaining = limit - total
            if remaining <= 0:
                break
            content = content[:remaining]
            total += len(content)
            result.append((path.relative_to(root).as_posix(), content))
        return result
