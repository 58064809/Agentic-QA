from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from harness.domain.models import (
    ExecutionEnvironmentPolicy,
    ExecutionProfile,
    normalize_workspace_id,
)
from harness.infrastructure.persistence.common import atomic_text

UTC = timezone.utc


class WorkspaceFilesystemRepository:
    def __init__(self, repo_root: Path | str) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.root = self.repo_root / "workspaces"

    def workspace_path(self, workspace: str) -> Path:
        workspace = normalize_workspace_id(workspace)
        path = (self.root / workspace).resolve()
        if path.parent != self.root.resolve():
            raise ValueError("workspace 路径越界")
        return path

    def init_workspace(self, workspace: str, *, quality_policies: list[str]) -> Path:
        workspace = normalize_workspace_id(workspace)
        path = self.workspace_path(workspace)
        if path.exists():
            raise FileExistsError(f"workspace 已存在: {workspace}")
        for relative in ("sources", "runs", "candidates", "reviews", "published", "memory"):
            (path / relative).mkdir(parents=True, exist_ok=False)
        atomic_text(
            path / "workspace.yml",
            yaml.safe_dump(
                {
                    "schema_version": "agentic-qa.harness.workspace.v2",
                    "id": workspace,
                    "created_at": datetime.now(tz=UTC).isoformat(),
                    "quality_policies": quality_policies,
                    "rag": {"provider": "local-lexical"},
                    "execution": {"environments": {}},
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
                f"workspace 不存在: {workspace}；先运行 agentic-qa workspace create {workspace}"
            )
        return path

    def workspace_config(self, workspace: str) -> dict[str, Any]:
        path = self.require_workspace(workspace) / "workspace.yml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("workspace.yml must contain an object")
        if payload.get("schema_version") != "agentic-qa.harness.workspace.v2":
            raise ValueError("workspace.yml v1 is not supported; create a v2 workspace")
        if payload.get("id") != normalize_workspace_id(workspace):
            raise ValueError("workspace.yml id does not match its directory")
        return payload

    def validate_execution_profile(
        self,
        workspace: str,
        profile: ExecutionProfile,
    ) -> ExecutionEnvironmentPolicy | None:
        if profile.environment == "analysis-only":
            return None
        payload = self.workspace_config(workspace)
        execution = payload.get("execution") or {}
        if not isinstance(execution, dict):
            raise ValueError("workspace.yml execution must be an object")
        environments = execution.get("environments") or {}
        if not isinstance(environments, dict):
            raise ValueError("workspace.yml execution.environments must be an object")
        raw_policy = environments.get(profile.environment)
        if raw_policy is None:
            raise PermissionError(
                f"execution environment is not configured in workspace.yml: {profile.environment}"
            )
        policy = ExecutionEnvironmentPolicy.model_validate(raw_policy)
        if profile.base_url_env != policy.base_url_env:
            raise PermissionError("execution profile base_url_env does not match workspace policy")
        disallowed = sorted(set(profile.allowed_http_methods) - set(policy.allowed_http_methods))
        if disallowed:
            raise PermissionError(
                f"execution profile requests disallowed HTTP methods: {', '.join(disallowed)}"
            )
        if profile.allow_ui_mutations and not policy.allow_ui_mutations:
            raise PermissionError("workspace policy does not allow UI mutations")
        if profile.request_timeout_seconds > policy.max_request_timeout_seconds:
            raise PermissionError("execution profile timeout exceeds workspace policy")
        return policy
