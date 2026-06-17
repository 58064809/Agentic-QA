from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NodeSpec:
    id: str
    type: str
    handler: str


@dataclass(frozen=True)
class EdgeSpec:
    source: str
    target: str
    condition: str | None = None


@dataclass(frozen=True)
class WorkflowSpec:
    id: str
    name: str
    version: int
    input: dict[str, str] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    nodes: list[NodeSpec] = field(default_factory=list)
    edges: list[EdgeSpec] = field(default_factory=list)
    source_path: str | None = None
