from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from runtime.graph.app import default_repo_root
from runtime.graph.nodes.artifact_writer import artifact_writer_node
from runtime.graph.nodes.context_loader import context_loader_node
from runtime.graph.nodes.human_review import human_review_node
from runtime.graph.nodes.intent_router import intent_router_node
from runtime.graph.nodes.metadata_update import metadata_update_node
from runtime.graph.nodes.quality_checker import testcase_quality_check_node
from runtime.graph.nodes.testcase_generation import testcase_generation_node
from runtime.graph.nodes.workflow_selector import workflow_selector_node
from runtime.graph.state import (
    GraphQAWorkflowState,
    QAWorkflowState,
    from_graph_state,
    to_graph_state,
)
from runtime.records.run_recorder import record_runtime_result
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


def build_testcase_generation_graph(repo_root: Path):
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
    graph.add_node("testcase_generation_node", _wrap_node(testcase_generation_node))
    graph.add_node(
        "testcase_quality_check_node",
        _wrap_node(lambda state: testcase_quality_check_node(state, root)),
    )
    graph.add_node("human_review_node", _wrap_node(human_review_node))
    graph.add_node(
        "artifact_writer_node",
        _wrap_node(lambda state: artifact_writer_node(state, root)),
    )
    graph.add_node("metadata_update_node", _wrap_node(metadata_update_node))

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
    graph.add_conditional_edges(
        "context_loader_node",
        _route_errors,
        {"ok": "testcase_generation_node", "error": END},
    )
    graph.add_edge("testcase_generation_node", "testcase_quality_check_node")
    graph.add_conditional_edges(
        "testcase_quality_check_node",
        _route_quality,
        {"ok": "human_review_node", "error": END},
    )
    graph.add_edge("human_review_node", "artifact_writer_node")
    graph.add_edge("artifact_writer_node", "metadata_update_node")
    graph.add_edge("metadata_update_node", END)
    return graph.compile()


def run_langgraph_testcase_generation_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    record_run: bool = True,
) -> RuntimeResult:
    root = (repo_root or default_repo_root()).resolve()
    initial_state = QAWorkflowState(
        user_input=user_input,
        prd_path=Path(prd_path).as_posix(),
        dry_run=not approve_write,
        approve_write=approve_write,
        orchestration="LangGraph StateGraph",
    )
    graph = build_testcase_generation_graph(root)
    graph_state = graph.invoke(to_graph_state(initial_state))
    result = RuntimeResult.from_state(from_graph_state(graph_state))
    if record_run:
        return record_runtime_result(result, root)
    return result
