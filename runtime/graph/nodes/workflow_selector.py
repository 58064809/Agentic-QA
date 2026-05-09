from __future__ import annotations

from pathlib import Path

from runtime.graph.state import QAWorkflowState

TESTCASE_WORKFLOW_FILES = [
    "workflows/10-runtime-testcase-generation-workflow.md",
    "workflows/02-testcase-generation-workflow.md",
]


def workflow_selector_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    state.record_node("workflow_selector_node")
    if state.errors:
        return state

    state.workflow_files = list(TESTCASE_WORKFLOW_FILES)
    for relative_path in state.workflow_files:
        if not (repo_root / relative_path).is_file():
            state.errors.append(f"缺少 Runtime 工作流文件: {relative_path}")
    return state
