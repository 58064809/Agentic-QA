from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime.graph.state import QAWorkflowState, from_graph_state, to_graph_state  # noqa: E402
from runtime.workflow.builder import build_graph_from_spec  # noqa: E402
from runtime.workflow.schema import (  # noqa: E402
    EXECUTABLE_NODE_TYPES,
    EdgeSpec,
    NodeSpec,
    WorkflowSpec,
)


def node_a(state: QAWorkflowState) -> QAWorkflowState:
    state.record_node("node_a")
    return state


def node_b(state: QAWorkflowState) -> QAWorkflowState:
    state.record_node("node_b")
    return state


def node_c(state: QAWorkflowState) -> QAWorkflowState:
    state.record_node("node_c")
    return state


def qa_state(**kwargs) -> QAWorkflowState:
    return QAWorkflowState(
        user_input="run unit workflow",
        prd_path="prd/demo-requirement",
        **kwargs,
    )


def workflow_spec(
    *,
    nodes: list[NodeSpec] | None = None,
    edges: list[EdgeSpec] | None = None,
) -> WorkflowSpec:
    return WorkflowSpec(
        id="unit_workflow",
        name="Unit Workflow",
        version=1,
        nodes=nodes
        or [
            NodeSpec(id="a", type="python", handler="test_workflow_builder.node_a"),
            NodeSpec(id="b", type="python", handler="test_workflow_builder.node_b"),
            NodeSpec(id="c", type="python", handler="test_workflow_builder.node_c"),
        ],
        edges=edges or [EdgeSpec(source="start", target="a")],
    )


def graph_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def test_build_graph_rejects_unknown_handler():
    spec = workflow_spec(
        nodes=[NodeSpec(id="a", type="python", handler="test_workflow_builder.missing")]
    )

    with pytest.raises(ValueError, match="handler 不存在或不可调用"):
        build_graph_from_spec(spec, REPO_ROOT)


@pytest.mark.parametrize("node_type", sorted(EXECUTABLE_NODE_TYPES))
def test_build_graph_accepts_executable_node_types(node_type):
    spec = workflow_spec(
        nodes=[
            NodeSpec(id="a", type=node_type, handler="test_workflow_builder.node_a"),
        ],
        edges=[EdgeSpec(source="start", target="a"), EdgeSpec(source="a", target="end")],
    )

    graph = build_graph_from_spec(spec, REPO_ROOT)
    state = from_graph_state(
        graph.invoke(to_graph_state(qa_state()), config=graph_config(f"type-{node_type}"))
    )

    assert state.executed_nodes == ["node_a"]


def test_workflow_spec_rejects_unsupported_node_type():
    with pytest.raises(ValidationError, match="unsupported node type"):
        NodeSpec(id="a", type="shell", handler="test_workflow_builder.node_a")


def test_build_graph_rejects_unknown_condition():
    spec = workflow_spec(
        edges=[
            EdgeSpec(source="start", target="a"),
            EdgeSpec(source="a", target="b", condition="missing_condition"),
        ]
    )

    with pytest.raises(ValueError, match="未知 Workflow condition"):
        build_graph_from_spec(spec, REPO_ROOT)


def test_workflow_spec_rejects_duplicate_node_id():
    with pytest.raises(ValidationError, match="重复 node id"):
        workflow_spec(
            nodes=[
                NodeSpec(id="a", type="python", handler="test_workflow_builder.node_a"),
                NodeSpec(id="a", type="python", handler="test_workflow_builder.node_b"),
            ]
        )


def test_build_graph_rejects_edge_target_that_does_not_exist():
    spec = workflow_spec(edges=[EdgeSpec(source="start", target="missing")])

    with pytest.raises(ValueError, match="edge target 不存在"):
        build_graph_from_spec(spec, REPO_ROOT)


def test_build_graph_rejects_mixed_fixed_and_conditional_edges_from_same_source():
    spec = workflow_spec(
        edges=[
            EdgeSpec(source="start", target="a"),
            EdgeSpec(source="a", target="b"),
            EdgeSpec(source="a", target="c", condition="default"),
        ]
    )

    with pytest.raises(ValueError, match="混合固定边和条件边"):
        build_graph_from_spec(spec, REPO_ROOT)


def test_build_graph_rejects_multiple_default_edges_from_same_source():
    spec = workflow_spec(
        edges=[
            EdgeSpec(source="start", target="a"),
            EdgeSpec(source="a", target="b", condition="default"),
            EdgeSpec(source="a", target="c", condition="default"),
        ]
    )

    with pytest.raises(ValueError, match="只能有一个 default edge"):
        build_graph_from_spec(spec, REPO_ROOT)


def test_default_edge_runs_when_no_other_condition_matches():
    spec = workflow_spec(
        edges=[
            EdgeSpec(source="start", target="a"),
            EdgeSpec(source="a", target="b", condition="has_errors"),
            EdgeSpec(source="a", target="c", condition="default"),
            EdgeSpec(source="b", target="end"),
            EdgeSpec(source="c", target="end"),
        ]
    )

    graph = build_graph_from_spec(spec, REPO_ROOT)
    state = from_graph_state(
        graph.invoke(to_graph_state(qa_state()), config=graph_config("default-fallback"))
    )

    assert state.executed_nodes == ["node_a", "node_c"]


def test_default_edge_is_evaluated_after_explicit_conditions():
    spec = workflow_spec(
        edges=[
            EdgeSpec(source="start", target="a"),
            EdgeSpec(source="a", target="c", condition="default"),
            EdgeSpec(source="a", target="b", condition="has_errors"),
            EdgeSpec(source="b", target="end"),
            EdgeSpec(source="c", target="end"),
        ]
    )

    graph = build_graph_from_spec(spec, REPO_ROOT)
    initial_state = qa_state(errors=["boom"])
    state = from_graph_state(
        graph.invoke(to_graph_state(initial_state), config=graph_config("default-order"))
    )

    assert state.executed_nodes == ["node_a", "node_b"]
