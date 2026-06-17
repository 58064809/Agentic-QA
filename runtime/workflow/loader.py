from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from runtime.workflow.schema import EdgeSpec, NodeSpec, WorkflowSpec

WORKFLOW_GLOB = "*.workflow.yml"


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是 YAML 对象")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是 YAML 列表")
    return value


def workflow_dir(repo_root: Path) -> Path:
    return repo_root / "workflows" / "runtime"


def workflow_path_for_id(repo_root: Path, workflow_id: str) -> Path:
    for path in workflow_dir(repo_root).glob(WORKFLOW_GLOB):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data = _require_mapping(raw, path.as_posix())
        if data.get("id") == workflow_id:
            return path
    raise FileNotFoundError(f"找不到 Workflow DSL: {workflow_id}")


def load_workflow_spec(path: Path | str) -> WorkflowSpec:
    workflow_path = Path(path)
    raw = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
    data = _require_mapping(raw, workflow_path.as_posix())

    nodes = []
    for item in _require_list(data.get("nodes"), "nodes"):
        node = _require_mapping(item, "node")
        nodes.append(
            NodeSpec(
                id=str(node.get("id") or ""),
                type=str(node.get("type") or ""),
                handler=str(node.get("handler") or ""),
            )
        )

    edges = []
    for item in _require_list(data.get("edges"), "edges"):
        edge = _require_mapping(item, "edge")
        edges.append(
            EdgeSpec(
                source=str(edge.get("from") or ""),
                target=str(edge.get("to") or ""),
                condition=str(edge["condition"]) if edge.get("condition") else None,
            )
        )

    return WorkflowSpec(
        id=str(data.get("id") or ""),
        name=str(data.get("name") or ""),
        version=int(data.get("version") or 0),
        input=dict(data.get("input") or {}),
        state=dict(data.get("state") or {}),
        nodes=nodes,
        edges=edges,
        source_path=workflow_path.as_posix(),
    )


def load_workflow_spec_by_id(repo_root: Path, workflow_id: str) -> WorkflowSpec:
    return load_workflow_spec(workflow_path_for_id(repo_root, workflow_id))
