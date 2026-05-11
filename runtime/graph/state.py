from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

from runtime.llm.config import default_llm_metadata


def default_requirement_normalization() -> dict[str, Any]:
    return {
        "performed": False,
        "source_path": None,
        "output_path": None,
        "source_type": None,
        "skipped_reason": None,
    }


def default_prototype_notes() -> dict[str, Any]:
    return {
        "loaded": False,
        "path": None,
        "requirement_has_images": False,
        "warning": None,
    }


class GraphQAWorkflowState(TypedDict, total=False):
    user_input: str
    prd_path: str
    task_type: str | None
    intent: str | None
    workflow_files: list[str]
    loaded_files: dict[str, str]
    draft_artifact: str | None
    draft_artifacts: dict[str, str]
    output_paths: dict[str, str]
    artifacts: list[dict[str, Any]]
    quality_errors: list[str]
    review_status: str
    output_path: str | None
    dry_run: bool
    approve_write: bool
    use_llm: bool
    fast_llm: bool
    max_llm_calls: int
    llm: dict[str, Any]
    requirement_normalization: dict[str, Any]
    prototype_notes: dict[str, Any]
    errors: list[str]
    warnings: list[str]
    executed_nodes: list[str]
    wrote_file: bool
    orchestration: str
    run_id: str | None
    run_record_dir: str | None
    run_summary_json: str | None
    run_summary_md: str | None
    debug_dir: str | None
    debug_artifacts: dict[str, str]


@dataclass
class QAWorkflowState:
    user_input: str
    prd_path: str
    task_type: str | None = None
    intent: str | None = None
    workflow_files: list[str] = field(default_factory=list)
    loaded_files: dict[str, str] = field(default_factory=dict)
    draft_artifact: str | None = None
    draft_artifacts: dict[str, str] = field(default_factory=dict)
    output_paths: dict[str, str] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    quality_errors: list[str] = field(default_factory=list)
    review_status: str = "not_started"
    output_path: str | None = None
    dry_run: bool = True
    approve_write: bool = False
    use_llm: bool = False
    fast_llm: bool = False
    max_llm_calls: int = 0
    llm: dict[str, Any] = field(default_factory=default_llm_metadata)
    requirement_normalization: dict[str, Any] = field(
        default_factory=default_requirement_normalization
    )
    prototype_notes: dict[str, Any] = field(default_factory=default_prototype_notes)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    executed_nodes: list[str] = field(default_factory=list)
    wrote_file: bool = False
    orchestration: str = "LangGraph StateGraph"
    run_id: str | None = None
    run_record_dir: str | None = None
    run_summary_json: str | None = None
    run_summary_md: str | None = None
    debug_dir: str | None = None
    debug_artifacts: dict[str, str] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return not self.errors and not self.quality_errors

    def record_node(self, name: str) -> None:
        self.executed_nodes.append(name)


def to_graph_state(state: QAWorkflowState) -> GraphQAWorkflowState:
    return {
        "user_input": state.user_input,
        "prd_path": state.prd_path,
        "task_type": state.task_type,
        "intent": state.intent,
        "workflow_files": list(state.workflow_files),
        "loaded_files": dict(state.loaded_files),
        "draft_artifact": state.draft_artifact,
        "draft_artifacts": dict(state.draft_artifacts),
        "output_paths": dict(state.output_paths),
        "artifacts": [dict(artifact) for artifact in state.artifacts],
        "quality_errors": list(state.quality_errors),
        "review_status": state.review_status,
        "output_path": state.output_path,
        "dry_run": state.dry_run,
        "approve_write": state.approve_write,
        "use_llm": state.use_llm,
        "fast_llm": state.fast_llm,
        "max_llm_calls": state.max_llm_calls,
        "llm": dict(state.llm),
        "requirement_normalization": dict(state.requirement_normalization),
        "prototype_notes": dict(state.prototype_notes),
        "errors": list(state.errors),
        "warnings": list(state.warnings),
        "executed_nodes": list(state.executed_nodes),
        "wrote_file": state.wrote_file,
        "orchestration": state.orchestration,
        "run_id": state.run_id,
        "run_record_dir": state.run_record_dir,
        "run_summary_json": state.run_summary_json,
        "run_summary_md": state.run_summary_md,
        "debug_dir": state.debug_dir,
        "debug_artifacts": dict(state.debug_artifacts),
    }


def _get_list(graph_state: GraphQAWorkflowState, key: str) -> list[Any]:
    value = graph_state.get(key, [])
    return list(value) if isinstance(value, list) else []


def _get_str_dict(graph_state: GraphQAWorkflowState, key: str) -> dict[str, str]:
    value = graph_state.get(key, {})
    return dict(value) if isinstance(value, dict) else {}


def _get_any_dict(graph_state: GraphQAWorkflowState, key: str) -> dict[str, Any]:
    value = graph_state.get(key, {})
    return dict(value) if isinstance(value, dict) else {}


def _get_artifacts(graph_state: GraphQAWorkflowState) -> list[dict[str, Any]]:
    value = graph_state.get("artifacts", [])
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def from_graph_state(graph_state: GraphQAWorkflowState) -> QAWorkflowState:
    return QAWorkflowState(
        user_input=str(graph_state.get("user_input", "")),
        prd_path=str(graph_state.get("prd_path", "")),
        task_type=graph_state.get("task_type"),
        intent=graph_state.get("intent"),
        workflow_files=_get_list(graph_state, "workflow_files"),
        loaded_files=_get_str_dict(graph_state, "loaded_files"),
        draft_artifact=graph_state.get("draft_artifact"),
        draft_artifacts=_get_str_dict(graph_state, "draft_artifacts"),
        output_paths=_get_str_dict(graph_state, "output_paths"),
        artifacts=_get_artifacts(graph_state),
        quality_errors=_get_list(graph_state, "quality_errors"),
        review_status=str(graph_state.get("review_status", "not_started")),
        output_path=graph_state.get("output_path"),
        dry_run=bool(graph_state.get("dry_run", True)),
        approve_write=bool(graph_state.get("approve_write", False)),
        use_llm=bool(graph_state.get("use_llm", False)),
        fast_llm=bool(graph_state.get("fast_llm", False)),
        max_llm_calls=int(graph_state.get("max_llm_calls", 0) or 0),
        llm={**default_llm_metadata(), **_get_any_dict(graph_state, "llm")},
        requirement_normalization={
            **default_requirement_normalization(),
            **_get_any_dict(graph_state, "requirement_normalization"),
        },
        prototype_notes={
            **default_prototype_notes(),
            **_get_any_dict(graph_state, "prototype_notes"),
        },
        errors=_get_list(graph_state, "errors"),
        warnings=_get_list(graph_state, "warnings"),
        executed_nodes=_get_list(graph_state, "executed_nodes"),
        wrote_file=bool(graph_state.get("wrote_file", False)),
        orchestration=str(graph_state.get("orchestration", "LangGraph StateGraph")),
        run_id=graph_state.get("run_id"),
        run_record_dir=graph_state.get("run_record_dir"),
        run_summary_json=graph_state.get("run_summary_json"),
        run_summary_md=graph_state.get("run_summary_md"),
        debug_dir=graph_state.get("debug_dir"),
        debug_artifacts=_get_str_dict(graph_state, "debug_artifacts"),
    )
