"""DEPRECATED legacy hard-coded LangGraph workflow.

New runtime workflows must use runtime.workflow.runner + workflows/runtime/*.workflow.yml.
This module is kept only for temporary backward compatibility with old tests/runs.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from runtime.graph.app import default_repo_root
from runtime.graph.nodes.artifact_generator import (
    SKIP_GENERATION_INTENTS,
    artifact_generation_node,
)
from runtime.graph.nodes.artifact_writer import artifact_writer_node
from runtime.graph.nodes.context_loader import context_loader_node
from runtime.graph.nodes.human_review import human_review_node
from runtime.graph.nodes.intent_router import intent_router_node
from runtime.graph.nodes.metadata_update import metadata_update_node
from runtime.graph.nodes.quality_checker import testcase_quality_check_node
from runtime.graph.nodes.workflow_selector import workflow_selector_node
from runtime.graph.state import (
    GraphQAWorkflowState,
    QAWorkflowState,
    from_graph_state,
    to_graph_state,
)
from runtime.records.run_recorder import (
    append_review_event,
    create_run_identity,
    load_checkpointer,
    record_runtime_result,
    run_record_dir_for,
)
from runtime.schemas.runtime_result import RuntimeResult


def _wrap_node(
    node: Callable[[QAWorkflowState], QAWorkflowState],
) -> Callable[[GraphQAWorkflowState], GraphQAWorkflowState]:
    def wrapped(graph_state: GraphQAWorkflowState) -> GraphQAWorkflowState:
        state = from_graph_state(graph_state)
        node(state)
        return to_graph_state(state)

    return wrapped


def _route_errors(graph_state: GraphQAWorkflowState) -> str:
    return "error" if graph_state.get("errors") else "ok"


def _route_quality(graph_state: GraphQAWorkflowState) -> str:
    if graph_state.get("errors") or graph_state.get("quality_errors"):
        return "error"
    return "ok"


def _route_after_context_loader(graph_state: GraphQAWorkflowState) -> str:
    """根据意图决定下一步：archive 类不生成产物，其余走生成节点。"""
    if graph_state.get("errors"):
        return "error"
    intent = graph_state.get("intent")
    if intent in SKIP_GENERATION_INTENTS:
        return "skip"
    return "generate"


def _route_after_human_review(graph_state: GraphQAWorkflowState) -> str:
    if graph_state.get("errors") or graph_state.get("quality_errors"):
        return "error"
    if (
        graph_state.get("review_status") in {"approved", "write_approved"}
        and graph_state.get("next_action") == "promote"
    ):
        return "write"
    return "end"


def _interrupts_from_graph_state(graph_state: GraphQAWorkflowState) -> list[Any]:
    value = graph_state.get("__interrupt__")  # type: ignore[typeddict-item]
    return list(value) if isinstance(value, list) else []


def _state_from_graph_output(graph_state: GraphQAWorkflowState) -> QAWorkflowState:
    state = from_graph_state(graph_state)
    interrupts = _interrupts_from_graph_state(graph_state)
    if interrupts:
        interrupt_payloads = [
            {
                "id": str(getattr(item, "id", "")),
                "value": getattr(item, "value", None),
            }
            for item in interrupts
        ]
        state.review_status = "needs_human_review"
        state.next_action = "wait_for_review"
        state.run_status = "interrupted"
        state.human_review = {
            "status": "needs_human_review",
            "decision": None,
            "reviewed_by": None,
            "review_notes": None,
            "interrupt": interrupt_payloads,
        }
        if "human_review_node" not in state.executed_nodes:
            state.executed_nodes.append("human_review_node")
    elif state.run_status in {"not_started", "approved", "write_approved", "dry_run"}:
        state.run_status = "completed" if state.success else "failed"
    return state


def build_testcase_generation_graph(repo_root: Path, checkpointer: MemorySaver | None = None):
    root = repo_root.resolve()
    graph = StateGraph(GraphQAWorkflowState)
    graph.add_node("intent_router_node", _wrap_node(intent_router_node))
    graph.add_node(
        "workflow_selector_node",
        _wrap_node(lambda state: workflow_selector_node(state, root)),
    )
    graph.add_node(
        "context_loader_node",
        _wrap_node(lambda state: context_loader_node(state, root)),
    )
    graph.add_node("artifact_generation_node", _wrap_node(artifact_generation_node))
    graph.add_node(
        "testcase_quality_check_node",
        _wrap_node(lambda state: testcase_quality_check_node(state, root)),
    )
    graph.add_node("human_review_node", _wrap_node(lambda state: human_review_node(state, root)))
    graph.add_node(
        "artifact_writer_node",
        _wrap_node(lambda state: artifact_writer_node(state, root)),
    )
    graph.add_node(
        "metadata_update_node",
        _wrap_node(lambda state: metadata_update_node(state, root)),
    )

    graph.add_edge(START, "intent_router_node")
    graph.add_conditional_edges(
        "intent_router_node",
        _route_errors,
        {"ok": "workflow_selector_node", "error": END},
    )
    graph.add_conditional_edges(
        "workflow_selector_node",
        _route_errors,
        {"ok": "context_loader_node", "error": END},
    )
    # 意图感知路由：archive → human_review，其余 → artifact_generation
    graph.add_conditional_edges(
        "context_loader_node",
        _route_after_context_loader,
        {
            "generate": "artifact_generation_node",
            "skip": "human_review_node",
            "error": END,
        },
    )
    graph.add_edge("artifact_generation_node", "testcase_quality_check_node")
    graph.add_conditional_edges(
        "testcase_quality_check_node",
        _route_quality,
        {"ok": "human_review_node", "error": END},
    )
    graph.add_conditional_edges(
        "human_review_node",
        _route_after_human_review,
        {"write": "artifact_writer_node", "end": END, "error": END},
    )
    graph.add_edge("artifact_writer_node", "metadata_update_node")
    graph.add_edge("metadata_update_node", END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())


def run_langgraph_testcase_generation_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    debug_approve_preview_write: bool = False,
    record_run: bool = True,
) -> RuntimeResult:
    root = (repo_root or default_repo_root()).resolve()
    run_id, thread_id = create_run_identity()
    preview_write = debug_approve_preview_write or approve_write
    initial_state = QAWorkflowState(
        user_input=user_input,
        prd_path=Path(prd_path).as_posix(),
        dry_run=not preview_write,
        approve_write=preview_write,
        debug_approve_preview_write=preview_write,
        orchestration="LangGraph StateGraph",
        run_id=run_id if record_run else None,
        thread_id=thread_id,
        run_status="running",
    )
    checkpointer = MemorySaver()
    graph = build_testcase_generation_graph(root, checkpointer=checkpointer)
    graph_config = {"configurable": {"thread_id": thread_id}}
    graph_state = graph.invoke(to_graph_state(initial_state), config=graph_config)
    result = RuntimeResult.from_state(_state_from_graph_output(graph_state))
    if record_run:
        return record_runtime_result(
            result,
            root,
            graph_state=graph_state,
            checkpointer=checkpointer,
        )
    return result


def resume_langgraph_testcase_generation_workflow(
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
    run_record_dir = run_record_dir_for(root, run_id)
    checkpointer = load_checkpointer(run_record_dir)
    graph = build_testcase_generation_graph(root, checkpointer=checkpointer)
    thread_id = run_id
    graph_config = {"configurable": {"thread_id": thread_id}}

    if action is None and user_input is None:
        snapshot = graph.get_state(graph_config)
        state = from_graph_state(dict(snapshot.values))
        state.run_id = run_id
        state.thread_id = thread_id
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
            graph_state=to_graph_state(state),
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
    previous_state = from_graph_state(dict(previous_snapshot.values))
    previous_status = (
        "needs_human_review" if previous_snapshot.next else previous_state.review_status
    )
    previous_run_status = "interrupted" if previous_snapshot.next else previous_state.run_status
    graph_state = graph.invoke(Command(resume=decision), config=graph_config)
    result = RuntimeResult.from_state(_state_from_graph_output(graph_state))
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
        graph_state=graph_state,
        checkpointer=checkpointer,
    )
