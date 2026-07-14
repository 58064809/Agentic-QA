from __future__ import annotations

from collections.abc import Callable

from runtime.graph.nodes.workflow_context import (
    TASK_ANALYSIS,
    TASK_ANALYSIS_AND_TESTCASES,
    TASK_API_DISCOVERY_REPORT,
    TASK_API_TEST_DRAFT,
    TASK_QA_REPORT,
    TASK_TESTCASE_GENERATION,
    TASK_UI_TEST_DRAFT,
)
from runtime.graph.state import QAWorkflowState

Condition = Callable[[QAWorkflowState], bool]
DEFAULT_CONDITION = "default"


def no_errors(state: QAWorkflowState) -> bool:
    return not state.errors


def has_errors(state: QAWorkflowState) -> bool:
    return bool(state.errors)


def default(_state: QAWorkflowState) -> bool:
    return True


def no_quality_errors(state: QAWorkflowState) -> bool:
    return not state.errors and not state.quality_errors


def has_quality_errors(state: QAWorkflowState) -> bool:
    return not state.errors and bool(state.quality_errors)


def review_approved(state: QAWorkflowState) -> bool:
    return not state.errors and state.review_status == "approved" and state.next_action == "promote"


def review_needs_changes(state: QAWorkflowState) -> bool:
    return not state.errors and state.review_status == "needs_changes"


def review_rejected(state: QAWorkflowState) -> bool:
    return not state.errors and state.review_status == "rejected"


def review_waiting(state: QAWorkflowState) -> bool:
    return (
        not state.errors
        and state.review_status == "needs_human_review"
        and state.next_action == "wait_for_review"
    )


def task_is_analysis_or_combined(state: QAWorkflowState) -> bool:
    return no_errors(state) and state.task_type in {TASK_ANALYSIS, TASK_ANALYSIS_AND_TESTCASES}


def task_is_analysis(state: QAWorkflowState) -> bool:
    return no_errors(state) and state.task_type == TASK_ANALYSIS


def task_is_testcase_generation(state: QAWorkflowState) -> bool:
    return no_errors(state) and state.task_type == TASK_TESTCASE_GENERATION


def task_is_api_test_draft(state: QAWorkflowState) -> bool:
    return no_errors(state) and state.task_type == TASK_API_TEST_DRAFT


def task_is_ui_test_draft(state: QAWorkflowState) -> bool:
    return no_errors(state) and state.task_type == TASK_UI_TEST_DRAFT


def task_is_api_discovery_report(state: QAWorkflowState) -> bool:
    return no_errors(state) and state.task_type == TASK_API_DISCOVERY_REPORT


def task_is_qa_report(state: QAWorkflowState) -> bool:
    return no_errors(state) and state.task_type == TASK_QA_REPORT


def task_is_analysis_and_testcases(state: QAWorkflowState) -> bool:
    return no_quality_errors(state) and state.task_type == TASK_ANALYSIS_AND_TESTCASES


def ready_to_write_preview(state: QAWorkflowState) -> bool:
    if not no_quality_errors(state):
        return False
    return state.review_status in {"approved", "write_approved"} and state.next_action == "promote"


CONDITIONS: dict[str, Condition] = {
    DEFAULT_CONDITION: default,
    "has_errors": has_errors,
    "has_quality_errors": has_quality_errors,
    "no_errors": no_errors,
    "no_quality_errors": no_quality_errors,
    "ready_to_write_preview": ready_to_write_preview,
    "review_approved": review_approved,
    "review_needs_changes": review_needs_changes,
    "review_rejected": review_rejected,
    "review_waiting": review_waiting,
    "task_is_analysis": task_is_analysis,
    "task_is_analysis_or_combined": task_is_analysis_or_combined,
    "task_is_api_discovery_report": task_is_api_discovery_report,
    "task_is_api_test_draft": task_is_api_test_draft,
    "task_is_analysis_and_testcases": task_is_analysis_and_testcases,
    "task_is_qa_report": task_is_qa_report,
    "task_is_testcase_generation": task_is_testcase_generation,
    "task_is_ui_test_draft": task_is_ui_test_draft,
}


def get_condition(name: str) -> Condition:
    try:
        return CONDITIONS[name]
    except KeyError as exc:
        raise ValueError(f"未知 Workflow condition: {name}") from exc
