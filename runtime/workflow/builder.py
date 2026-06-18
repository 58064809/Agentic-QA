from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from runtime.graph.state import (
    GraphQAWorkflowState,
    QAWorkflowState,
    from_graph_state,
    to_graph_state,
)
from runtime.workflow.conditions import DEFAULT_CONDITION, get_condition
from runtime.workflow.registry import call_handler, import_handler
from runtime.workflow.schema import EdgeSpec, WorkflowSpec


def _graph_node_name(node_id: str) -> str:
    if node_id == "start":
        return START
    if node_id == "end":
        return END
    return node_id


def _wrap_handler(
    handler_path: str,
    repo_root: Path,
) -> Callable[[GraphQAWorkflowState], GraphQAWorkflowState]:
    handler = import_handler(handler_path)

    def wrapped(graph_state: GraphQAWorkflowState) -> GraphQAWorkflowState:
        state = from_graph_state(graph_state)
        result = call_handler(handler, state, repo_root)
        return to_graph_state(result)

    return wrapped


def _validate_workflow(spec: WorkflowSpec) -> None:
    if not spec.id:
        raise ValueError("Workflow id 不能为空")
    node_ids = {node.id for node in spec.nodes}
    if len(node_ids) != len(spec.nodes):
        raise ValueError(f"Workflow {spec.id} 存在重复 node id")
    for node in spec.nodes:
        if node.type != "python":
            raise ValueError(f"Workflow {spec.id} 仅支持 python node: {node.id}")
        if not node.handler:
            raise ValueError(f"Workflow {spec.id} node 缺少 handler: {node.id}")
        import_handler(node.handler)
    for edge in spec.edges:
        if edge.source not in node_ids | {"start"}:
            raise ValueError(f"Workflow {spec.id} edge source 不存在: {edge.source}")
        if edge.target not in node_ids | {"end"}:
            raise ValueError(f"Workflow {spec.id} edge target 不存在: {edge.target}")
        if edge.condition:
            get_condition(edge.condition)


def _conditional_router(edges: list[EdgeSpec]) -> Callable[[GraphQAWorkflowState], str]:
    default_edges = [edge for edge in edges if edge.condition == DEFAULT_CONDITION]
    conditional_edges = [edge for edge in edges if edge.condition != DEFAULT_CONDITION]

    def route(graph_state: GraphQAWorkflowState) -> str:
        for edge in conditional_edges:
            if edge.condition and get_condition(edge.condition)(graph_state):
                return edge.target
        if default_edges:
            return default_edges[0].target
        return "end"

    return route


def _validate_source_edges(spec: WorkflowSpec, source: str, edges: list[EdgeSpec]) -> None:
    conditional = [edge for edge in edges if edge.condition]
    fixed = [edge for edge in edges if not edge.condition]
    if conditional and fixed:
        raise ValueError(f"Workflow {spec.id} 不支持同一 source 混合固定边和条件边: {source}")
    default_edges = [edge for edge in conditional if edge.condition == DEFAULT_CONDITION]
    if len(default_edges) > 1:
        raise ValueError(f"Workflow {spec.id} 同一 source 只能有一个 default edge: {source}")


def build_graph_from_spec(
    spec: WorkflowSpec,
    repo_root: Path,
    checkpointer: MemorySaver | None = None,
):
    _validate_workflow(spec)
    root = repo_root.resolve()
    graph = StateGraph(GraphQAWorkflowState)

    for node in spec.nodes:
        graph.add_node(node.id, _wrap_handler(node.handler, root))

    edges_by_source: dict[str, list[EdgeSpec]] = defaultdict(list)
    for edge in spec.edges:
        edges_by_source[edge.source].append(edge)

    for source, edges in edges_by_source.items():
        _validate_source_edges(spec, source, edges)
        conditional = [edge for edge in edges if edge.condition]
        fixed = [edge for edge in edges if not edge.condition]
        if conditional:
            path_map = {edge.target: _graph_node_name(edge.target) for edge in conditional}
            path_map["end"] = END
            graph.add_conditional_edges(
                _graph_node_name(source),
                _conditional_router(conditional),
                path_map,
            )
        else:
            for edge in fixed:
                graph.add_edge(_graph_node_name(edge.source), _graph_node_name(edge.target))

    return graph.compile(checkpointer=checkpointer or MemorySaver())


def apply_workflow_state_defaults(state: QAWorkflowState, spec: WorkflowSpec) -> QAWorkflowState:
    for key, value in spec.state.items():
        if not hasattr(state, key):
            raise ValueError(f"Workflow {spec.id} state 字段不存在: {key}")
        setattr(state, key, value)
    return state
