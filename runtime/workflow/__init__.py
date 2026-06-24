from __future__ import annotations

from typing import Any

from runtime.workflow.loader import load_workflow_spec
from runtime.workflow.schema import EdgeSpec, NodeSpec, WorkflowSpec

__all__ = [
    "EdgeSpec",
    "NodeSpec",
    "WorkflowSpec",
    "load_workflow_spec",
    "resume_workflow_for_run",
    "run_workflow_by_id",
]


def __getattr__(name: str) -> Any:
    if name in {"resume_workflow_for_run", "run_workflow_by_id"}:
        from runtime.workflow import runner

        return getattr(runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
