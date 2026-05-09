from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


class GraphQAWorkflowState(TypedDict, total=False):
    user_input: str
    prd_path: str
    intent: str | None
    workflow_files: list[str]
    loaded_files: dict[str, str]
    draft_artifact: str | None
    quality_errors: list[str]
    review_status: str
    output_path: str | None
    dry_run: bool
    approve_write: bool
    errors: list[str]
    warnings: list[str]
    executed_nodes: list[str]
    wrote_file: bool
    orchestration: str
    run_id: str | None
    run_record_dir: str | None
    run_summary_json: str | None
    run_summary_md: str | None


@dataclass
class QAWorkflowState:
    user_input: str
    prd_path: str
    intent: str | None = None
    workflow_files: list[str] = field(default_factory=list)
    loaded_files: dict[str, str] = field(default_factory=dict)
    draft_artifact: str | None = None
    quality_errors: list[str] = field(default_factory=list)
    review_status: str = "not_started"
    output_path: str | None = None
    dry_run: bool = True
    approve_write: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    executed_nodes: list[str] = field(default_factory=list)
    wrote_file: bool = False
    orchestration: str = "LangGraph StateGraph"
    run_id: str | None = None
    run_record_dir: str | None = None
    run_summary_json: str | None = None
    run_summary_md: str | None = None

    @property
    def success(self) -> bool:
        return not self.errors and not self.quality_errors

    def record_node(self, name: str) -> None:
        self.executed_nodes.append(name)


def to_graph_state(state: QAWorkflowState) -> GraphQAWorkflowState:
    return {
        "user_input": state.user_input,
        "prd_path": state.prd_path,
        "intent": state.intent,
        "workflow_files": list(state.workflow_files),
        "loaded_files": dict(state.loaded_files),
        "draft_artifact": state.draft_artifact,
        "quality_errors": list(state.quality_errors),
        "review_status": state.review_status,
        "output_path": state.output_path,
        "dry_run": state.dry_run,
        "approve_write": state.approve_write,
        "errors": list(state.errors),
        "warnings": list(state.warnings),
        "executed_nodes": list(state.executed_nodes),
        "wrote_file": state.wrote_file,
        "orchestration": state.orchestration,
        "run_id": state.run_id,
        "run_record_dir": state.run_record_dir,
        "run_summary_json": state.run_summary_json,
        "run_summary_md": state.run_summary_md,
    }


def _get_list(graph_state: GraphQAWorkflowState, key: str) -> list[Any]:
    value = graph_state.get(key, [])
    return list(value) if isinstance(value, list) else []


def _get_dict(graph_state: GraphQAWorkflowState, key: str) -> dict[str, str]:
    value = graph_state.get(key, {})
    return dict(value) if isinstance(value, dict) else {}


def from_graph_state(graph_state: GraphQAWorkflowState) -> QAWorkflowState:
    return QAWorkflowState(
        user_input=str(graph_state.get("user_input", "")),
        prd_path=str(graph_state.get("prd_path", "")),
        intent=graph_state.get("intent"),
        workflow_files=_get_list(graph_state, "workflow_files"),
        loaded_files=_get_dict(graph_state, "loaded_files"),
        draft_artifact=graph_state.get("draft_artifact"),
        quality_errors=_get_list(graph_state, "quality_errors"),
        review_status=str(graph_state.get("review_status", "not_started")),
        output_path=graph_state.get("output_path"),
        dry_run=bool(graph_state.get("dry_run", True)),
        approve_write=bool(graph_state.get("approve_write", False)),
        errors=_get_list(graph_state, "errors"),
        warnings=_get_list(graph_state, "warnings"),
        executed_nodes=_get_list(graph_state, "executed_nodes"),
        wrote_file=bool(graph_state.get("wrote_file", False)),
        orchestration=str(graph_state.get("orchestration", "LangGraph StateGraph")),
        run_id=graph_state.get("run_id"),
        run_record_dir=graph_state.get("run_record_dir"),
        run_summary_json=graph_state.get("run_summary_json"),
        run_summary_md=graph_state.get("run_summary_md"),
    )
