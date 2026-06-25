from __future__ import annotations

import json
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from runtime.config import load_app_config
from runtime.graph.app import default_repo_root
from runtime.graph.nodes.mvp_context_loader import TASK_MVP
from runtime.graph.state import QAWorkflowState
from runtime.llm.config import OpenAICompatibleConfig
from runtime.records.run_recorder import (
    append_review_event,
    create_run_identity,
    load_checkpointer,
    record_runtime_result,
    run_record_dir_for,
)
from runtime.schemas.runtime_result import RuntimeResult
from runtime.workflow.builder import apply_workflow_state_defaults, build_graph_from_spec
from runtime.workflow.catalog import DEFAULT_WORKFLOW_REGISTRY
from runtime.workflow.loader import load_workflow_spec_by_id


def task_type_for_recorded_run(repo_root: Path, run_id: str) -> str | None:
    state_path = run_record_dir_for(repo_root, run_id) / "run-state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"未找到运行记录: {state_path.as_posix()}")
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    result = payload.get("result", {})
    if not isinstance(result, dict):
        return None
    task_type = result.get("task_type")
    return str(task_type) if task_type else None


def workflow_id_for_task_type(task_type: str | None) -> str:
    return DEFAULT_WORKFLOW_REGISTRY.workflow_id_for_task_type(task_type)


def _interrupt_metadata(state: QAWorkflowState) -> list[dict]:
    """Extract LangGraph interrupt info from the Pydantic model (extra field)."""
    raw = state.model_extra.get("__interrupt__") if state.model_extra else None
    interrupts = list(raw) if isinstance(raw, list) else []
    return [
        {"id": str(getattr(item, "id", "")), "value": getattr(item, "value", None)}
        for item in interrupts
    ]


def _finalize_state(state: QAWorkflowState) -> QAWorkflowState:
    """Post-process state after graph execution: detect interrupts / completion."""
    interrupts = _interrupt_metadata(state)
    if interrupts:
        state.review_status = "needs_human_review"
        state.next_action = "wait_for_review"
        state.run_status = "interrupted"
        state.human_review = {
            "status": "needs_human_review",
            "decision": None,
            "reviewed_by": None,
            "review_notes": None,
            "interrupt": interrupts,
        }
        if "human_review_node" not in state.executed_nodes:
            state.executed_nodes.append("human_review_node")
    elif state.run_status in {"not_started", "approved", "write_approved", "dry_run"}:
        state.run_status = "completed" if state.success else "failed"
    return state


def run_workflow_by_id(
    workflow_id: str,
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    debug_approve_preview_write: bool = False,
    record_run: bool = True,
    use_llm: bool = True,
) -> RuntimeResult:
    root = (repo_root or default_repo_root()).resolve()
    spec = load_workflow_spec_by_id(root, workflow_id)
    run_id, thread_id = create_run_identity()
    app_config = load_app_config(root)
    config = OpenAICompatibleConfig.from_app_config(app_config.llm)
    preview_write = debug_approve_preview_write or approve_write

    initial_state = QAWorkflowState(
        user_input=user_input,
        prd_path=Path(prd_path).as_posix(),
        dry_run=not preview_write,
        approve_write=preview_write,
        debug_approve_preview_write=preview_write,
        use_llm=use_llm,
        llm=config.to_metadata(enabled=use_llm),
        orchestration=f"YAML WorkflowSpec: {workflow_id}",
        run_id=run_id if record_run else None,
        thread_id=thread_id,
        run_status="running",
    )
    apply_workflow_state_defaults(initial_state, spec)
    initial_state.max_llm_calls = 2 if initial_state.task_type == TASK_MVP else 1

    checkpointer = MemorySaver()
    graph = build_graph_from_spec(spec, root, checkpointer=checkpointer)
    graph_config = {"configurable": {"thread_id": thread_id}}
    final_state = QAWorkflowState.model_validate(graph.invoke(initial_state, config=graph_config))
    _finalize_state(final_state)
    result = RuntimeResult.from_state(final_state)
    if record_run:
        return record_runtime_result(
            result,
            root,
            graph_state=final_state.model_dump(mode="json"),
            checkpointer=checkpointer,
        )
    return result


def resume_workflow_for_run(
    run_id: str,
    *,
    action: str | None = None,
    user_input: str | None = None,
    reviewed_by: str = "user",
    review_notes: str | None = None,
    target_artifact: str | None = None,
    repo_root: Path | None = None,
) -> RuntimeResult:
    root = (repo_root or default_repo_root()).resolve()
    task_type = task_type_for_recorded_run(root, run_id)
    return resume_workflow_by_id(
        workflow_id_for_task_type(task_type),
        run_id,
        action=action,
        user_input=user_input,
        reviewed_by=reviewed_by,
        review_notes=review_notes,
        target_artifact=target_artifact,
        repo_root=root,
    )


def resume_workflow_by_id(
    workflow_id: str,
    run_id: str,
    *,
    action: str | None = None,
    user_input: str | None = None,
    reviewed_by: str = "user",
    review_notes: str | None = None,
    target_artifact: str | None = None,
    repo_root: Path | None = None,
) -> RuntimeResult:
    root = (repo_root or default_repo_root()).resolve()
    spec = load_workflow_spec_by_id(root, workflow_id)
    run_record_dir = run_record_dir_for(root, run_id)
    checkpointer = load_checkpointer(run_record_dir)
    graph = build_graph_from_spec(spec, root, checkpointer=checkpointer)
    graph_config = {"configurable": {"thread_id": run_id}}

    if action is None and user_input is None:
        snapshot = graph.get_state(graph_config)
        state = QAWorkflowState.model_validate(snapshot.values)
        state.run_id = run_id
        state.thread_id = run_id
        if snapshot.next:
            state.review_status = "needs_human_review"
            state.next_action = "wait_for_review"
            state.run_status = "interrupted"
            state.warnings.append("当前运行仍在人工审核暂停点，请使用 approve 或 reject。")
        else:
            state.run_status = "completed" if state.success else "failed"
        result = RuntimeResult.from_state(state)
        return record_runtime_result(
            result,
            root,
            graph_state=state.model_dump(mode="json"),
            checkpointer=checkpointer,
        )

    decision = {
        "action": action,
        "user_input": user_input,
        "reviewed_by": reviewed_by,
        "review_notes": review_notes,
        "target_artifact": target_artifact,
    }
    previous_snapshot = graph.get_state(graph_config)
    previous_state = QAWorkflowState.model_validate(previous_snapshot.values)
    previous_status = (
        "needs_human_review" if previous_snapshot.next else previous_state.review_status
    )
    previous_run_status = "interrupted" if previous_snapshot.next else previous_state.run_status
    final_state = QAWorkflowState.model_validate(
        graph.invoke(Command(resume=decision), config=graph_config)
    )
    _finalize_state(final_state)
    result = RuntimeResult.from_state(final_state)
    append_review_event(
        result,
        root,
        action=action,
        reviewed_by=reviewed_by,
        review_notes=review_notes,
        previous_status=previous_status,
        previous_run_status=previous_run_status,
    )
    return record_runtime_result(
        result,
        root,
        graph_state=final_state.model_dump(mode="json"),
        checkpointer=checkpointer,
    )
