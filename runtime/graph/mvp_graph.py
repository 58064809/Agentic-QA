from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from runtime.graph.app import default_repo_root
from runtime.graph.nodes.human_review import human_review_node
from runtime.graph.nodes.metadata_update import metadata_update_node
from runtime.graph.nodes.mvp_artifact_writer import mvp_artifact_writer_node
from runtime.graph.nodes.mvp_context_loader import (
    TASK_ANALYSIS,
    TASK_MVP,
    TASK_TESTCASE_GENERATION,
    mvp_command_router_node,
    mvp_context_loader_node,
    mvp_workflow_selector_node,
)
from runtime.graph.nodes.mvp_generation import (
    requirement_analysis_generation_node,
    testcase_generation_mvp_node,
)
from runtime.graph.nodes.mvp_quality import (
    requirement_analysis_quality_check_node,
    testcase_mvp_quality_check_node,
)
from runtime.graph.nodes.requirement_normalizer import normalize_requirement_document
from runtime.graph.state import (
    GraphQAWorkflowState,
    QAWorkflowState,
    from_graph_state,
    to_graph_state,
)
from runtime.llm.config import OpenAICompatibleConfig
from runtime.records.run_recorder import (
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


def _route_after_context(graph_state: GraphQAWorkflowState) -> str:
    if graph_state.get("errors"):
        return "error"
    task_type = graph_state.get("task_type")
    if task_type in {TASK_ANALYSIS, TASK_MVP}:
        return "analysis"
    return "testcases"


def _route_after_analysis_quality(graph_state: GraphQAWorkflowState) -> str:
    if graph_state.get("errors") or graph_state.get("quality_errors"):
        return "error"
    if graph_state.get("task_type") == TASK_MVP:
        return "testcases"
    return "review"


def _route_after_human_review(graph_state: GraphQAWorkflowState) -> str:
    if graph_state.get("errors") or graph_state.get("quality_errors"):
        return "error"
    if graph_state.get("review_status") == "approved":
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
    elif state.run_status in {"not_started", "approved"}:
        state.run_status = "completed" if state.success else "failed"
    return state


def build_mvp_generation_graph(repo_root: Path, checkpointer: MemorySaver | None = None):
    root = repo_root.resolve()
    graph = StateGraph(GraphQAWorkflowState)
    graph.add_node("mvp_command_router_node", _wrap_node(mvp_command_router_node))
    graph.add_node(
        "mvp_workflow_selector_node",
        _wrap_node(lambda state: mvp_workflow_selector_node(state, root)),
    )
    graph.add_node(
        "mvp_context_loader_node",
        _wrap_node(lambda state: mvp_context_loader_node(state, root)),
    )
    graph.add_node(
        "requirement_normalizer_node",
        _wrap_node(lambda state: normalize_requirement_document(state, root)),
    )
    graph.add_node(
        "requirement_analysis_generation_node",
        _wrap_node(requirement_analysis_generation_node),
    )
    graph.add_node(
        "requirement_analysis_quality_check_node",
        _wrap_node(lambda state: requirement_analysis_quality_check_node(state, root)),
    )
    graph.add_node("testcase_generation_node", _wrap_node(testcase_generation_mvp_node))
    graph.add_node(
        "testcase_quality_check_node",
        _wrap_node(lambda state: testcase_mvp_quality_check_node(state, root)),
    )
    graph.add_node("human_review_node", _wrap_node(human_review_node))
    graph.add_node(
        "mvp_artifact_writer_node",
        _wrap_node(lambda state: mvp_artifact_writer_node(state, root)),
    )
    graph.add_node("metadata_update_node", _wrap_node(metadata_update_node))

    graph.add_edge(START, "mvp_command_router_node")
    graph.add_conditional_edges(
        "mvp_command_router_node",
        _route_errors,
        {"ok": "mvp_workflow_selector_node", "error": END},
    )
    graph.add_conditional_edges(
        "mvp_workflow_selector_node",
        _route_errors,
        {"ok": "requirement_normalizer_node", "error": END},
    )
    graph.add_conditional_edges(
        "requirement_normalizer_node",
        _route_errors,
        {"ok": "mvp_context_loader_node", "error": END},
    )
    graph.add_conditional_edges(
        "mvp_context_loader_node",
        _route_after_context,
        {
            "analysis": "requirement_analysis_generation_node",
            "testcases": "testcase_generation_node",
            "error": END,
        },
    )
    graph.add_edge(
        "requirement_analysis_generation_node",
        "requirement_analysis_quality_check_node",
    )
    graph.add_conditional_edges(
        "requirement_analysis_quality_check_node",
        _route_after_analysis_quality,
        {
            "review": "human_review_node",
            "testcases": "testcase_generation_node",
            "error": END,
        },
    )
    graph.add_edge("testcase_generation_node", "testcase_quality_check_node")
    graph.add_conditional_edges(
        "testcase_quality_check_node",
        _route_quality,
        {"ok": "human_review_node", "error": END},
    )
    graph.add_conditional_edges(
        "human_review_node",
        _route_after_human_review,
        {"write": "mvp_artifact_writer_node", "end": END, "error": END},
    )
    graph.add_edge("mvp_artifact_writer_node", "metadata_update_node")
    graph.add_edge("metadata_update_node", END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())


def run_mvp_generation_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    task_type: str,
    repo_root: Path | None = None,
    approve_write: bool = False,
    record_run: bool = True,
    use_llm: bool = False,
) -> RuntimeResult:
    root = (repo_root or default_repo_root()).resolve()
    run_id, thread_id = create_run_identity()
    config = OpenAICompatibleConfig.from_env()
    max_llm_calls = 2 if task_type == TASK_MVP else 1
    initial_state = QAWorkflowState(
        user_input=user_input,
        prd_path=Path(prd_path).as_posix(),
        task_type=task_type,
        dry_run=not approve_write,
        approve_write=approve_write,
        use_llm=use_llm,
        max_llm_calls=max_llm_calls,
        llm=config.to_metadata(enabled=use_llm),
        orchestration="LangGraph StateGraph",
        run_id=run_id if record_run else None,
        thread_id=thread_id,
        run_status="running",
    )
    checkpointer = MemorySaver()
    graph = build_mvp_generation_graph(root, checkpointer=checkpointer)
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


def resume_mvp_generation_workflow(
    run_id: str,
    *,
    action: str | None = None,
    reviewed_by: str = "user",
    review_notes: str | None = None,
    repo_root: Path | None = None,
) -> RuntimeResult:
    root = (repo_root or default_repo_root()).resolve()
    run_record_dir = run_record_dir_for(root, run_id)
    checkpointer = load_checkpointer(run_record_dir)
    graph = build_mvp_generation_graph(root, checkpointer=checkpointer)
    thread_id = run_id
    graph_config = {"configurable": {"thread_id": thread_id}}

    if action is None:
        snapshot = graph.get_state(graph_config)
        state = from_graph_state(dict(snapshot.values))
        state.run_id = run_id
        state.thread_id = thread_id
        if snapshot.next:
            state.review_status = "needs_human_review"
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
        "reviewed_by": reviewed_by,
        "review_notes": review_notes,
    }
    graph_state = graph.invoke(Command(resume=decision), config=graph_config)
    result = RuntimeResult.from_state(_state_from_graph_output(graph_state))
    return record_runtime_result(
        result,
        root,
        graph_state=graph_state,
        checkpointer=checkpointer,
    )


def run_requirement_analysis_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    record_run: bool = True,
    use_llm: bool = False,
) -> RuntimeResult:
    return run_mvp_generation_workflow(
        user_input,
        prd_path,
        task_type=TASK_ANALYSIS,
        repo_root=repo_root,
        approve_write=approve_write,
        record_run=record_run,
        use_llm=use_llm,
    )


def run_mvp_testcase_generation_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    record_run: bool = True,
    use_llm: bool = False,
) -> RuntimeResult:
    return run_mvp_generation_workflow(
        user_input,
        prd_path,
        task_type=TASK_TESTCASE_GENERATION,
        repo_root=repo_root,
        approve_write=approve_write,
        record_run=record_run,
        use_llm=use_llm,
    )


def run_mvp_analysis_and_testcases_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    record_run: bool = True,
    use_llm: bool = False,
) -> RuntimeResult:
    return run_mvp_generation_workflow(
        user_input,
        prd_path,
        task_type=TASK_MVP,
        repo_root=repo_root,
        approve_write=approve_write,
        record_run=record_run,
        use_llm=use_llm,
    )
