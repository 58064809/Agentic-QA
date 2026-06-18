from __future__ import annotations

import pytest

from runtime.workflow.conditions import (
    DEFAULT_CONDITION,
    get_condition,
    has_errors,
    no_errors,
)


def test_builtin_conditions_report_error_state():
    state = {"errors": ["boom"]}

    assert has_errors(state)
    assert not no_errors(state)


def test_default_condition_is_available():
    assert get_condition(DEFAULT_CONDITION)({})


def test_unknown_condition_raises_clear_error():
    with pytest.raises(ValueError, match="未知 Workflow condition"):
        get_condition("missing_condition")
