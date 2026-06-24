from __future__ import annotations

from collections.abc import Callable

from runtime.graph.nodes.mvp_context_loader import (
    TASK_ANALYSIS,
    TASK_MVP,
    TASK_TESTCASE_GENERATION,
)
from runtime.graph.state import GraphQAWorkflowState

Condition = Callable[[GraphQAWorkflowState], bool]
DEFAULT_CONDITION = "default"


def no_errors(state: GraphQAWorkflowState) -> bool:
    return not state.get("errors")


def has_errors(state: GraphQAWorkflowState) -> bool:
    return bool(state.get("errors"))


def default(_state: GraphQAWorkflowState) -> bool:
    return True


def no_quality_errors(state: GraphQAWorkflowState) -> bool:
    return not state.get("errors") and not state.get("quality_errors")


def task_is_analysis_or_mvp(state: GraphQAWorkflowState) -> bool:
    return no_errors(state) and state.get("task_type") in {TASK_ANALYSIS, TASK_MVP}


def task_is_analysis(state: GraphQAWorkflowState) -> bool:
    return no_errors(state) and state.get("task_type") == TASK_ANALYSIS


def task_is_testcase_generation(state: GraphQAWorkflowState) -> bool:
    return no_errors(state) and state.get("task_type") == TASK_TESTCASE_GENERATION


def task_is_mvp(state: GraphQAWorkflowState) -> bool:
    return no_quality_errors(state) and state.get("task_type") == TASK_MVP


def ready_to_write_preview(state: GraphQAWorkflowState) -> bool:
    if not no_quality_errors(state):
        return False
    return (
        state.get("review_status") in {"approved", "write_approved"}
        and state.get("next_action") == "promote"
    )


CONDITIONS: dict[str, Condition] = {
    DEFAULT_CONDITION: default,
    "has_errors": has_errors,
    "no_errors": no_errors,
    "no_quality_errors": no_quality_errors,
    "ready_to_write_preview": ready_to_write_preview,
    "task_is_analysis": task_is_analysis,
    "task_is_analysis_or_mvp": task_is_analysis_or_mvp,
    "task_is_mvp": task_is_mvp,
    "task_is_testcase_generation": task_is_testcase_generation,
}


def get_condition(name: str) -> Condition:
    try:
        return CONDITIONS[name]
    except KeyError as exc:
        raise ValueError(f"未知 Workflow condition: {name}") from exc
