from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harness.domain.models import HarnessEvent, RunSnapshot
from harness.infrastructure.persistence.common import atomic_json
from harness.infrastructure.persistence.workspace_repository import WorkspaceFilesystemRepository

UTC = timezone.utc
SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class RunEventFilesystemRepository:
    def __init__(self, workspaces: WorkspaceFilesystemRepository) -> None:
        self.workspaces = workspaces

    def create_run(self, snapshot: RunSnapshot) -> None:
        workspace = self.workspaces.require_workspace(snapshot.workspace_id)
        run = workspace / "runs" / snapshot.run_id
        run.mkdir(parents=False, exist_ok=False)
        (run / "tool-calls").mkdir()
        (workspace / "candidates" / snapshot.run_id).mkdir()
        (workspace / "reviews" / snapshot.run_id).mkdir()
        atomic_json(run / "task.json", snapshot.request.model_dump(mode="json"))
        self.save_snapshot(snapshot)

    def save_snapshot(self, snapshot: RunSnapshot) -> None:
        run = self.workspaces.require_workspace(snapshot.workspace_id) / "runs" / snapshot.run_id
        snapshot.updated_at = datetime.now(tz=UTC)
        atomic_json(run / "state.json", snapshot.model_dump(mode="json"))
        if snapshot.plan is not None:
            atomic_json(run / "plan.json", snapshot.plan.model_dump(mode="json"))

    def next_event_sequence(self, workspace: str, run_id: str) -> int:
        path = self.workspaces.require_workspace(workspace) / "runs" / run_id / "events.jsonl"
        if not path.is_file():
            return 1
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip()) + 1

    def append_event(self, workspace: str, event: HarnessEvent) -> None:
        path = self.workspaces.require_workspace(workspace) / "runs" / event.run_id / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(event.model_dump_json() + "\n")

    def has_assessment_event(self, workspace: str, run_id: str, assessment_key: str) -> bool:
        path = self.workspaces.require_workspace(workspace) / "runs" / run_id / "events.jsonl"
        if not path.is_file():
            return False
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                payload.get("type") == "artifact_quality_evaluated"
                and (payload.get("data") or {}).get("assessment_key") == assessment_key
            ):
                return True
        return False

    def has_publication_event(self, workspace: str, run_id: str, publication_id: str) -> bool:
        path = self.workspaces.require_workspace(workspace) / "runs" / run_id / "events.jsonl"
        if not path.is_file():
            return False
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                payload.get("type") == "review_applied"
                and (payload.get("data") or {}).get("publication_id") == publication_id
            ):
                return True
        return False

    def write_tool_record(
        self,
        workspace: str,
        run_id: str,
        name: str,
        payload: dict[str, Any],
    ) -> Path:
        path = self.workspaces.require_workspace(workspace) / "runs" / run_id / "tool-calls" / name
        atomic_json(path, payload)
        return path

    def tool_records(self, workspace: str, run_id: str) -> list[dict[str, Any]]:
        root = self.workspaces.require_workspace(workspace) / "runs" / run_id / "tool-calls"
        records: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def load_snapshot(self, workspace: str, run_id: str) -> RunSnapshot:
        if not SAFE_RUN_ID.fullmatch(run_id):
            raise ValueError("run_id 不安全")
        path = self.workspaces.require_workspace(workspace) / "runs" / run_id / "state.json"
        if not path.is_file():
            raise FileNotFoundError(f"run 不存在: {run_id}")
        return RunSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
