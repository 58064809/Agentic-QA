"""Tests for workflow conditions (attribute-access API after State unification)."""

from __future__ import annotations

from runtime.graph.state import QAWorkflowState
from runtime.workflow.conditions import (
    DEFAULT_CONDITION,
    get_condition,
    has_errors,
    no_errors,
)


def test_builtin_conditions_report_error_state():
    state = QAWorkflowState()
    state.errors.append("boom")

    assert has_errors(state)
    assert not no_errors(state)


def test_default_condition_is_available():
    assert get_condition(DEFAULT_CONDITION)(QAWorkflowState())


def test_unknown_condition_raises_clear_error():
    import pytest

    with pytest.raises(ValueError, match="未知 Workflow condition"):
        get_condition("missing_condition")
