from __future__ import annotations

from pathlib import Path

import pytest

from runtime.graph.state import QAWorkflowState
from runtime.workflow.registry import call_handler, import_handler


def passthrough_handler(state: QAWorkflowState) -> QAWorkflowState:
    state.record_node("registry_passthrough_handler")
    return state


def test_import_handler_returns_callable():
    handler = import_handler("test_workflow_registry.passthrough_handler")

    assert handler is passthrough_handler


def test_import_handler_rejects_unknown_handler():
    with pytest.raises(ValueError, match="handler 不存在或不可调用"):
        import_handler("test_workflow_registry.missing_handler")


def test_import_handler_rejects_invalid_handler_path():
    with pytest.raises(ValueError, match="handler 路径非法"):
        import_handler("missing_handler")


def test_call_handler_returns_state_when_handler_returns_none():
    def none_handler(_state: QAWorkflowState) -> None:
        return None

    state = QAWorkflowState(user_input="run unit workflow", prd_path="prd/demo-requirement")

    assert call_handler(none_handler, state, repo_root=Path.cwd()) is state
