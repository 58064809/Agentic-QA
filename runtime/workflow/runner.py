from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.types import Command

from runtime.config import load_app_config
from runtime.graph.app import default_repo_root
from runtime.graph.nodes.workflow_context import TASK_ANALYSIS_AND_TESTCASES
from runtime.graph.state import QAWorkflowState
from runtime.llm.config import OpenAICompatibleConfig
from runtime.records.run_recorder import (
    append_review_event,
    close_checkpointer,
    create_checkpointer,
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
    result = recorded_run_result(repo_root, run_id)
    task_type = result.get("task_type")
    return str(task_type) if task_type else None


def recorded_run_result(repo_root: Path, run_id: str) -> dict[str, object]:
    state_path = run_record_dir_for(repo_root, run_id) / "run-state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"未找到运行记录: {state_path.as_posix()}")
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    result = payload.get("result", {})
    if not isinstance(result, dict):
        return {}
    return result


def workflow_id_for_recorded_run(repo_root: Path, run_id: str) -> str:
    result = recorded_run_result(repo_root, run_id)
    orchestration = str(result.get("orchestration") or "")
    prefix = "YAML WorkflowSpec: "
    if orchestration.startswith(prefix):
        return orchestration.removeprefix(prefix).strip()
    intent = result.get("intent")
    if isinstance(intent, str) and intent in DEFAULT_WORKFLOW_REGISTRY.registered_task_types():
        return workflow_id_for_task_type(intent)
    return workflow_id_for_task_type(str(result.get("task_type") or ""))


def thread_id_for_recorded_run(repo_root: Path, run_id: str) -> str:
    result = recorded_run_result(repo_root, run_id)
    thread_id = result.get("thread_id")
    return str(thread_id) if thread_id else run_id


def workflow_id_for_task_type(task_type: str | None) -> str:
    return DEFAULT_WORKFLOW_REGISTRY.workflow_id_for_task_type(task_type)


def _langsmith_enabled(app_config) -> bool:
    observability = app_config.observability
    if observability.provider.strip().lower() != "langsmith":
        return False
    if observability.enabled:
        return True
    return os.getenv("LANGSMITH_TRACING", "").strip().lower() in {"1", "true", "yes", "on"} or (
        os.getenv("LANGCHAIN_TRACING_V2", "").strip().lower() in {"1", "true", "yes", "on"}
    )


def _configure_langsmith_environment(app_config) -> None:
    observability = app_config.observability
    if not _langsmith_enabled(app_config):
        return
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGSMITH_ENDPOINT", observability.endpoint)
    os.environ.setdefault("LANGCHAIN_ENDPOINT", observability.endpoint)
    os.environ.setdefault("LANGSMITH_PROJECT", observability.project)
    os.environ.setdefault("LANGCHAIN_PROJECT", observability.project)
    api_key = os.getenv(observability.api_key_env, "").strip()
    if api_key:
        os.environ.setdefault("LANGSMITH_API_KEY", api_key)
        os.environ.setdefault("LANGCHAIN_API_KEY", api_key)


def _graph_config(
    thread_id: str,
    *,
    workflow_id: str | None = None,
    run_id: str | None = None,
    app_config=None,
) -> dict[str, object]:
    config: dict[str, object] = {"configurable": {"thread_id": thread_id}}
    if app_config is None or not _langsmith_enabled(app_config):
        return config
    observability = app_config.observability
    tags = list(dict.fromkeys([*observability.tags, workflow_id or "workflow"]))
    config.update(
        {
            "run_name": workflow_id or "agentic-qa-workflow",
            "tags": tags,
            "metadata": {
                "project": app_config.project.name,
                "env": app_config.project.env,
                "workflow_id": workflow_id,
                "run_id": run_id,
                "thread_id": thread_id,
            },
        }
    )
    return config


def _checkpointer_kwargs(app_config) -> dict[str, object]:
    return {
        "storage": app_config.runtime.checkpointer,
        "postgres_dsn_env": app_config.runtime.checkpoint_postgres_dsn_env,
        "postgres_setup": app_config.runtime.checkpoint_postgres_setup,
    }


def _state_from_checkpoint_or_default(
    graph,
    graph_config: dict[str, dict[str, str]],
    default_state: QAWorkflowState,
) -> QAWorkflowState:
    try:
        snapshot = graph.get_state(graph_config)
    except Exception:
        return default_state
    if snapshot and snapshot.values:
        return QAWorkflowState.model_validate(snapshot.values)
    return default_state


@dataclass(frozen=True)
class WorkflowStreamResult:
    state: QAWorkflowState
    executed_nodes: list[str]
    interrupts: Any = None


class WorkflowStreamError(RuntimeError):
    def __init__(
        self,
        original: Exception,
        *,
        state: QAWorkflowState,
        executed_nodes: list[str],
        interrupts: Any = None,
    ) -> None:
        super().__init__(str(original))
        self.original = original
        self.state = state
        self.executed_nodes = executed_nodes
        self.interrupts = interrupts


def _node_names_from_stream_chunk(chunk: Any) -> list[str]:
    payload = chunk
    if (
        isinstance(chunk, tuple)
        and len(chunk) == 2
        and isinstance(chunk[0], tuple)
        and isinstance(chunk[1], dict)
    ):
        payload = chunk[1]

    if not isinstance(payload, dict):
        return []

    nodes = []
    for node_name in payload:
        node = str(node_name)
        if not node or node.startswith("__"):
            continue
        nodes.append(node)
    return nodes


def _stream_graph_updates(
    graph,
    input_value: Any,
    graph_config: dict[str, dict[str, str]],
    default_state: QAWorkflowState,
) -> WorkflowStreamResult:
    executed_nodes: list[str] = []
    interrupts: Any = None
    try:
        for chunk in graph.stream(
            input_value,
            config=graph_config,
            stream_mode="updates",
            subgraphs=True,
        ):
            payload = chunk[1] if isinstance(chunk, tuple) and len(chunk) == 2 else chunk
            if isinstance(payload, dict) and "__interrupt__" in payload:
                interrupts = payload["__interrupt__"]
            executed_nodes.extend(_node_names_from_stream_chunk(chunk))
    except Exception as exc:
        state = _state_from_checkpoint_or_default(graph, graph_config, default_state)
        if interrupts is not None:
            state.model_extra["__interrupt__"] = interrupts
        raise WorkflowStreamError(
            exc,
            state=state,
            executed_nodes=executed_nodes,
            interrupts=interrupts,
        ) from exc

    state = _state_from_checkpoint_or_default(graph, graph_config, default_state)
    if interrupts is not None:
        state.model_extra["__interrupt__"] = interrupts
    return WorkflowStreamResult(
        state=state,
        executed_nodes=executed_nodes,
        interrupts=interrupts,
    )


def _interrupt_metadata(state: QAWorkflowState) -> list[dict]:
    """Extract LangGraph interrupt info from the Pydantic model (extra field)."""
    raw = state.model_extra.get("__interrupt__") if state.model_extra else None
    interrupts = list(raw) if isinstance(raw, list | tuple) else []
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
    elif state.run_status in {
        "not_started",
        "running",
        "approved",
        "write_approved",
        "dry_run",
    }:
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
    run_record_dir = run_record_dir_for(root, run_id) if record_run else None
    app_config = load_app_config(root)
    _configure_langsmith_environment(app_config)
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
    initial_state.max_llm_calls = 2 if initial_state.task_type == TASK_ANALYSIS_AND_TESTCASES else 1

    try:
        checkpointer = create_checkpointer(
            run_record_dir,
            **_checkpointer_kwargs(app_config),
        )
    except RuntimeError as exc:
        initial_state.errors.append(str(exc))
        initial_state.run_status = "failed"
        initial_state.next_action = "retry"
        result = RuntimeResult.from_state(initial_state)
        if record_run:
            return record_runtime_result(
                result,
                root,
                graph_state=initial_state.model_dump(mode="json"),
                checkpointer=None,
            )
        return result
    try:
        graph = build_graph_from_spec(spec, root, checkpointer=checkpointer)
        graph_config = _graph_config(
            thread_id,
            workflow_id=workflow_id,
            run_id=run_id if record_run else None,
            app_config=app_config,
        )
        try:
            stream_result = _stream_graph_updates(graph, initial_state, graph_config, initial_state)
            final_state = stream_result.state
            executed_nodes = stream_result.executed_nodes
        except Exception as exc:
            if isinstance(exc, WorkflowStreamError):
                final_state = exc.state
                executed_nodes = exc.executed_nodes
                original = exc.original
            else:
                final_state = _state_from_checkpoint_or_default(graph, graph_config, initial_state)
                executed_nodes = []
                original = exc
            final_state.run_id = run_id if record_run else None
            final_state.thread_id = thread_id
            final_state.errors.append(f"Workflow 执行异常，可修复后重试: {original}")
            final_state.run_status = "failed"
            final_state.next_action = "retry"
        _finalize_state(final_state)
        result = RuntimeResult.from_state(
            final_state,
            executed_nodes=executed_nodes,
        )
        if record_run:
            return record_runtime_result(
                result,
                root,
                graph_state=final_state.model_dump(mode="json"),
                checkpointer=checkpointer,
            )
        return result
    finally:
        close_checkpointer(checkpointer)


def resume_workflow_for_run(
    run_id: str,
    *,
    action: str | None = None,
    user_input: str | None = None,
    resume_payload: dict[str, object] | None = None,
    reviewed_by: str = "user",
    review_notes: str | None = None,
    target_artifact: str | None = None,
    repo_root: Path | None = None,
) -> RuntimeResult:
    root = (repo_root or default_repo_root()).resolve()
    return resume_workflow_by_id(
        workflow_id_for_recorded_run(root, run_id),
        run_id,
        action=action,
        user_input=user_input,
        resume_payload=resume_payload,
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
    resume_payload: dict[str, object] | None = None,
    reviewed_by: str = "user",
    review_notes: str | None = None,
    target_artifact: str | None = None,
    repo_root: Path | None = None,
) -> RuntimeResult:
    root = (repo_root or default_repo_root()).resolve()
    spec = load_workflow_spec_by_id(root, workflow_id)
    run_record_dir = run_record_dir_for(root, run_id)
    app_config = load_app_config(root)
    _configure_langsmith_environment(app_config)
    checkpointer = load_checkpointer(
        run_record_dir,
        **_checkpointer_kwargs(app_config),
    )
    try:
        graph = build_graph_from_spec(spec, root, checkpointer=checkpointer)
        thread_id = thread_id_for_recorded_run(root, run_id)
        graph_config = _graph_config(
            thread_id,
            workflow_id=workflow_id,
            run_id=run_id,
            app_config=app_config,
        )

        if action is None and user_input is None and resume_payload is None:
            snapshot = graph.get_state(graph_config)
            state = QAWorkflowState.model_validate(snapshot.values)
            state.run_id = run_id
            state.thread_id = thread_id
            if snapshot.next:
                state.review_status = "needs_human_review"
                state.next_action = "wait_for_review"
                state.run_status = "interrupted"
                state.warnings.append("当前运行仍在人工审核暂停点，请使用 approve 或 reject。")
            else:
                state.run_status = "completed" if state.success else "failed"
            previous = recorded_run_result(root, run_id)
            previous_nodes = previous.get("executed_nodes")
            result = RuntimeResult.from_state(
                state,
                executed_nodes=previous_nodes if isinstance(previous_nodes, list) else [],
            )
            return record_runtime_result(
                result,
                root,
                graph_state=state.model_dump(mode="json"),
                checkpointer=checkpointer,
            )

        decision = dict(resume_payload or {})
        decision.setdefault("action", action)
        decision.setdefault("user_input", user_input)
        decision.setdefault("reviewed_by", reviewed_by)
        decision.setdefault("review_notes", review_notes)
        decision.setdefault("target_artifact", target_artifact)
        previous_snapshot = graph.get_state(graph_config)
        previous_state = QAWorkflowState.model_validate(previous_snapshot.values)
        previous_status = (
            "needs_human_review" if previous_snapshot.next else previous_state.review_status
        )
        previous_run_status = "interrupted" if previous_snapshot.next else previous_state.run_status
        stream_result = _stream_graph_updates(
            graph,
            Command(resume=decision),
            graph_config,
            previous_state,
        )
        final_state = stream_result.state
        _finalize_state(final_state)
        result = RuntimeResult.from_state(
            final_state,
            executed_nodes=stream_result.executed_nodes,
        )
        append_review_event(
            result,
            root,
            action=str(decision.get("action") or decision.get("type") or action or ""),
            reviewed_by=str(decision.get("reviewed_by") or reviewed_by),
            review_notes=str(decision.get("review_notes") or review_notes or ""),
            previous_status=previous_status,
            previous_run_status=previous_run_status,
        )
        return record_runtime_result(
            result,
            root,
            graph_state=final_state.model_dump(mode="json"),
            checkpointer=checkpointer,
        )
    finally:
        close_checkpointer(checkpointer)


def retry_failed_workflow_for_run(
    run_id: str,
    *,
    user_input: str | None = None,
    repo_root: Path | None = None,
) -> RuntimeResult:
    """Retry a failed workflow with the same run_id/thread/checkpointer.

    This is intended for fault tolerance after the user fixes missing inputs,
    permissions, or transient environment problems. It does not bypass Review Gate.
    """
    root = (repo_root or default_repo_root()).resolve()
    workflow_id = workflow_id_for_recorded_run(root, run_id)
    spec = load_workflow_spec_by_id(root, workflow_id)
    run_record_dir = run_record_dir_for(root, run_id)
    app_config = load_app_config(root)
    _configure_langsmith_environment(app_config)
    checkpointer = load_checkpointer(
        run_record_dir,
        **_checkpointer_kwargs(app_config),
    )
    try:
        graph = build_graph_from_spec(spec, root, checkpointer=checkpointer)
        thread_id = thread_id_for_recorded_run(root, run_id)
        graph_config = _graph_config(
            thread_id,
            workflow_id=workflow_id,
            run_id=run_id,
            app_config=app_config,
        )
        previous = recorded_run_result(root, run_id)
        state = QAWorkflowState.model_validate(previous)
        state.run_id = run_id
        state.thread_id = thread_id
        if user_input:
            state.user_input = user_input
        state.errors = []
        state.quality_errors = []
        state.run_status = "running"
        state.review_status = "not_started"
        state.next_action = None
        state.human_review = {
            "status": "not_started",
            "decision": None,
            "reviewed_by": None,
            "review_notes": None,
            "interrupt": None,
        }
        state.warnings.append(f"从失败运行恢复重试: {run_id}")
        apply_workflow_state_defaults(state, spec)

        try:
            stream_result = _stream_graph_updates(graph, state, graph_config, state)
            final_state = stream_result.state
            executed_nodes = stream_result.executed_nodes
        except Exception as exc:
            if isinstance(exc, WorkflowStreamError):
                final_state = exc.state
                executed_nodes = exc.executed_nodes
                original = exc.original
            else:
                final_state = _state_from_checkpoint_or_default(graph, graph_config, state)
                executed_nodes = []
                original = exc
            final_state.run_id = run_id
            final_state.thread_id = thread_id
            final_state.errors.append(f"Workflow 重试仍然失败: {original}")
            final_state.run_status = "failed"
            final_state.next_action = "retry"
        _finalize_state(final_state)
        result = RuntimeResult.from_state(
            final_state,
            executed_nodes=executed_nodes,
        )
        return record_runtime_result(
            result,
            root,
            graph_state=final_state.model_dump(mode="json"),
            checkpointer=checkpointer,
        )
    finally:
        close_checkpointer(checkpointer)
