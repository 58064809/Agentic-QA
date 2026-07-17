"""Internal LangGraph graph definition.

Public contracts remain Pydantic models; LangGraph state and commands never cross
the :class:`harness.Harness` facade.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send


class HarnessState(TypedDict, total=False):
    run_id: str
    request: dict[str, Any]
    plan: dict[str, Any]
    pending_tasks: list[str]
    completed_tasks: list[str]
    results_by_task: dict[str, dict[str, Any]]
    task_results: Annotated[list[dict[str, Any]], operator.add]
    processed_results: int
    candidates: list[dict[str, Any]]
    review_status: dict[str, str]
    delegations: list[dict[str, Any]]
    status: str
    errors: Annotated[list[str], operator.add]
    review_decision: dict[str, Any]


def _ready(state: HarnessState) -> list[dict[str, Any]]:
    completed = set(state.get("completed_tasks", []))
    pending = set(state.get("pending_tasks", []))
    tasks = state.get("plan", {}).get("tasks", [])
    return [
        task
        for task in tasks
        if task.get("id") in pending and set(task.get("dependencies", [])).issubset(completed)
    ]


def _route_tasks(state: HarnessState) -> list[Send] | str:
    if not state.get("pending_tasks"):
        return "prepare_review"
    ready = _ready(state)
    if not ready:
        return "prepare_review"
    results = state.get("results_by_task", {})
    return [
        Send(
            "expert_agent",
            {
                "run_id": state["run_id"],
                "request": state["request"],
                "task": task,
                "dependencies": {
                    dependency: results[dependency]
                    for dependency in task.get("dependencies", [])
                    if dependency in results
                },
            },
        )
        for task in ready
    ]


def _route_review(state: HarnessState) -> str:
    return "review_gate" if state.get("status") == "needs_human_review" else END


def compile_harness_graph(
    *,
    checkpointer: Any,
    planner: Callable[..., Any],
    expert_agent: Callable[..., Any],
    supervisor: Callable[..., Any],
    prepare_review: Callable[..., Any],
    review_gate: Callable[..., Any],
    apply_review: Callable[..., Any],
) -> Any:
    builder = StateGraph(HarnessState)
    builder.add_node("planner", planner)
    builder.add_node("expert_agent", expert_agent)
    builder.add_node("qa_supervisor", supervisor)
    builder.add_node("prepare_review", prepare_review)
    builder.add_node("review_gate", review_gate)
    builder.add_node("apply_review", apply_review)
    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", _route_tasks)
    builder.add_edge("expert_agent", "qa_supervisor")
    builder.add_conditional_edges("qa_supervisor", _route_tasks)
    builder.add_edge("prepare_review", "review_gate")
    builder.add_edge("review_gate", "apply_review")
    builder.add_conditional_edges("apply_review", _route_review)
    return builder.compile(checkpointer=checkpointer)
