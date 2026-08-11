from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from harness.domain.schemas.api_execution_reporting import parse_api_execution_plan_json
from harness.infrastructure.api_published_source import PublishedApiSourceResolver
from harness.infrastructure.persistence.filesystem import FilesystemStore


class ExecutionPlanTamperedError(ValueError):
    code = "EXECUTION_PLAN_TAMPERED"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.code}: {message}")


class ExecutionSourceLinkageError(ValueError):
    code = "EXECUTION_SOURCE_LINKAGE_MISMATCH"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.code}: {message}")


@dataclass(frozen=True)
class ExecutionSourceSnapshot:
    workspace_id: str
    execution_id: str
    service: str
    environment: str
    source_publication_id: str
    source_history_path: str
    source_cases_sha256: str
    policy_sha256: str | None


class ExecutionSourceSnapshotResolver:
    def __init__(
        self,
        store: FilesystemStore,
        published_sources: PublishedApiSourceResolver,
    ) -> None:
        self._store = store
        self._published_sources = published_sources

    def resolve(self, workspace: str, execution_id: str) -> ExecutionSourceSnapshot:
        root = self._store.require_workspace(workspace).resolve()
        execution_root = (root / "executions" / execution_id).resolve()
        executions_root = (root / "executions").resolve()
        if execution_root.parent != executions_root:
            raise ExecutionPlanTamperedError("execution path is outside the workspace")
        manifest_path = execution_root / "manifest.json"
        plan_path = execution_root / "execution-plan.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            plan_bytes = plan_path.read_bytes()
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ExecutionPlanTamperedError("execution plan linkage is unavailable") from exc
        if not isinstance(manifest, dict):
            raise ExecutionPlanTamperedError("execution manifest is invalid")
        plan_file_sha256 = hashlib.sha256(plan_bytes).hexdigest()
        if manifest.get("execution_plan_sha256") != plan_file_sha256:
            raise ExecutionPlanTamperedError("execution plan file hash does not match manifest")
        try:
            plan = parse_api_execution_plan_json(plan_bytes.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise ExecutionPlanTamperedError("execution plan validation failed") from exc
        if plan.workspace_id != workspace or plan.execution_id != execution_id:
            raise ExecutionPlanTamperedError("execution plan identity does not match its path")
        if (
            manifest.get("workspace_id") != workspace
            or manifest.get("execution_id") != execution_id
            or manifest.get("environment") != plan.environment
        ):
            raise ExecutionSourceLinkageError("manifest identity differs from execution plan")
        publication_id = getattr(plan, "source_publication_id", None)
        history_path = getattr(plan, "source_history_path", None)
        source = self._published_sources.resolve_historical(
            workspace,
            publication_id=publication_id,
            history_path=history_path,
            expected_sha256=plan.source_cases_sha256,
        )
        if plan.source_cases_path != source.workspace_relative_path:
            raise ExecutionSourceLinkageError(
                "execution plan source path differs from historical publication"
            )
        if not plan.service or not plan.environment:
            raise ExecutionPlanTamperedError("execution plan report identity is incomplete")
        expected_manifest = {
            "source_publication_id": source.publication_id,
            "source_history_path": source.workspace_relative_path,
            "source_cases_sha256": source.content_sha256,
        }
        for field, expected in expected_manifest.items():
            recorded = manifest.get(field)
            if recorded is not None and recorded != expected:
                raise ExecutionSourceLinkageError(f"manifest {field} differs from execution plan")
        return ExecutionSourceSnapshot(
            workspace_id=workspace,
            execution_id=execution_id,
            service=plan.service,
            environment=plan.environment,
            source_publication_id=source.publication_id,
            source_history_path=source.workspace_relative_path,
            source_cases_sha256=source.content_sha256,
            policy_sha256=getattr(plan, "policy_sha256", None),
        )
