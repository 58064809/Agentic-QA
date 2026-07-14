from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from runtime.graph.state import QAWorkflowState
from runtime.workflow.conditions import DEFAULT_CONDITION, get_condition
from runtime.workflow.loader import load_workflow_spec_by_id
from runtime.workflow.registry import call_handler, import_handler
from runtime.workflow.schema import EXECUTABLE_NODE_TYPES, EdgeSpec, FailurePolicy, WorkflowSpec


def _graph_node_name(node_id: str) -> str:
    if node_id == "start":
        return START
    if node_id == "end":
        return END
    return node_id


def _apply_failure_policy(
    handler: Callable,
    handler_path: str,
    failure_policy: FailurePolicy,
    state: QAWorkflowState,
    repo_root: Path,
) -> QAWorkflowState:
    """Execute a node handler with failure_policy support."""
    last_error: Exception | None = None
    max_attempts = failure_policy.max_attempts

    for attempt in range(max_attempts):
        try:
            result = call_handler(handler, state, repo_root)
            if last_error and not result.errors:
                result.warnings.append(
                    f"节点恢复成功: {handler_path} (attempt {attempt + 1}/{max_attempts})"
                )
            return result
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts - 1:
                backoff = failure_policy.retry_backoff_seconds
                if backoff > 0:
                    time.sleep(backoff)
                continue
            break

    error_msg = f"节点执行失败 [{failure_policy.on_error}]: {handler_path}"
    if last_error:
        error_msg += f" — {last_error}"

    if failure_policy.on_error == "skip":
        state.warnings.append(error_msg)
        return state

    if failure_policy.on_error == "fail_workflow":
        state.errors.append(error_msg)
        return state

    if failure_policy.on_error == "wait_for_user":
        state.errors.append(error_msg)
        state.review_status = "needs_human_review"
        state.run_status = "interrupted"
        state.next_action = "wait_for_review"
        return state

    state.errors.append(error_msg)
    return state


def _wrap_handler(
    handler_path: str,
    repo_root: Path,
    failure_policy: FailurePolicy | None = None,
) -> Callable[[QAWorkflowState], QAWorkflowState]:
    """Wrap a Python handler for use as a LangGraph node.

    The handler receives the full ``QAWorkflowState`` directly. Handlers mutate
    state in-place and return it.
    """
    handler = import_handler(handler_path)

    def wrapped(state: QAWorkflowState) -> QAWorkflowState:
        if failure_policy is None:
            return call_handler(handler, state, repo_root)
        return _apply_failure_policy(handler, handler_path, failure_policy, state, repo_root)

    return wrapped


def _validate_workflow(spec: WorkflowSpec) -> None:
    if not spec.id:
        raise ValueError("Workflow id 不能为空")
    node_ids = {node.id for node in spec.nodes}
    if len(node_ids) != len(spec.nodes):
        raise ValueError(f"Workflow {spec.id} 存在重复 node id")
    for node in spec.nodes:
        if node.type not in EXECUTABLE_NODE_TYPES:
            supported = ", ".join(sorted(EXECUTABLE_NODE_TYPES))
            raise ValueError(
                f"Workflow {spec.id} node type unsupported: {node.type}; supported: {supported}"
            )
        if node.type == "subgraph":
            continue
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


def _conditional_router(edges: list[EdgeSpec]) -> Callable[[QAWorkflowState], str]:
    """Build a router that evaluates explicit conditions in YAML order."""
    default_edge = next(edge for edge in edges if edge.condition == DEFAULT_CONDITION)
    conditional_edges = [edge for edge in edges if edge.condition != DEFAULT_CONDITION]

    def route(state: QAWorkflowState) -> str:
        for edge in conditional_edges:
            if edge.condition and get_condition(edge.condition)(state):
                return edge.target
        return default_edge.target

    return route


def _validate_source_edges(spec: WorkflowSpec, source: str, edges: list[EdgeSpec]) -> None:
    conditional = [edge for edge in edges if edge.condition]
    fixed = [edge for edge in edges if not edge.condition]
    if conditional and fixed:
        raise ValueError(f"Workflow {spec.id} 不支持同一 source 混合固定边和条件边: {source}")
    if not conditional:
        return

    default_edges = [edge for edge in conditional if edge.condition == DEFAULT_CONDITION]
    if len(default_edges) != 1:
        raise ValueError(
            f"Workflow {spec.id} 条件路由必须且只能有一个 default edge: {source}"
        )


def build_graph_from_spec(
    spec: WorkflowSpec,
    repo_root: Path,
    checkpointer: MemorySaver | None = None,
    _stack: tuple[str, ...] = (),
):
    """Build a compiled LangGraph from a ``WorkflowSpec`` YAML definition."""
    _validate_workflow(spec)
    root = repo_root.resolve()
    graph = StateGraph(QAWorkflowState)

    for node in spec.nodes:
        if node.type == "subgraph":
            if not node.workflow:
                raise ValueError(f"Workflow {spec.id} subgraph node 缺少 workflow: {node.id}")
            current_stack = (*_stack, spec.id)
            if node.workflow in current_stack:
                cycle = " -> ".join((*current_stack, node.workflow))
                raise ValueError(f"Workflow subgraph 存在循环引用: {cycle}")
            sub_spec = load_workflow_spec_by_id(root, node.workflow)
            graph.add_node(
                node.id,
                build_graph_from_spec(
                    sub_spec,
                    root,
                    checkpointer=False,
                    _stack=current_stack,
                ),
            )
            continue
        graph.add_node(
            node.id,
            _wrap_handler(node.handler or "", root, failure_policy=node.failure_policy),
        )

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

    return graph.compile(checkpointer=checkpointer if checkpointer is not None else MemorySaver())


def apply_workflow_state_defaults(state: QAWorkflowState, spec: WorkflowSpec) -> QAWorkflowState:
    for key, value in spec.state.items():
        if not hasattr(state, key):
            raise ValueError(f"Workflow {spec.id} state 字段不存在: {key}")
        setattr(state, key, value)
    return state
