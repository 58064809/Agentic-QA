from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from runtime.workflow.loader import load_workflow_spec, load_workflow_spec_by_id


def write_workflow(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_load_workflow_spec_validates_required_fields(tmp_path):
    path = write_workflow(
        tmp_path / "broken.workflow.yml",
        """
id: broken
version: 1
nodes: []
edges: []
""",
    )

    with pytest.raises(ValidationError, match="name"):
        load_workflow_spec(path)


def test_load_workflow_spec_rejects_duplicate_edges(tmp_path):
    path = write_workflow(
        tmp_path / "duplicate-edge.workflow.yml",
        """
id: duplicate_edge
name: Duplicate Edge
version: 1
nodes:
  - id: a
    type: python
    handler: runtime.graph.nodes.mvp_context_loader.mvp_command_router_node
edges:
  - from: start
    to: a
  - from: start
    to: a
""",
    )

    with pytest.raises(ValidationError, match="重复 edge"):
        load_workflow_spec(path)


def test_load_workflow_spec_by_id_raises_when_workflow_id_does_not_exist(tmp_path):
    write_workflow(
        tmp_path / "workflows/runtime/example.workflow.yml",
        """
id: example
name: Example
version: 1
nodes:
  - id: a
    type: python
    handler: runtime.graph.nodes.mvp_context_loader.mvp_command_router_node
edges:
  - from: start
    to: a
""",
    )

    with pytest.raises(FileNotFoundError, match="找不到 Workflow DSL"):
        load_workflow_spec_by_id(tmp_path, "missing")
