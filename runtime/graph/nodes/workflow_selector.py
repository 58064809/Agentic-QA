from __future__ import annotations

from pathlib import Path

from runtime.graph.state import QAWorkflowState

# ── 按意图选择对应的工作流文件 ──────────────────────────────
INTENT_WORKFLOW_FILES: dict[str, list[str]] = {
    "requirement_analysis": ["workflows/01-requirement-analysis-workflow.md"],
    "testcase_generation": [
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/02-testcase-generation-workflow.md",
    ],
    "api_test_generation": [
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/03-api-test-generation-workflow.md",
    ],
    "ui_test_generation": [
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/04-ui-test-generation-workflow.md",
    ],
    "test_execution": ["workflows/10-runtime-testcase-generation-workflow.md", "workflows/05-test-execution-workflow.md"],
    "failure_analysis": ["workflows/10-runtime-testcase-generation-workflow.md", "workflows/06-failure-analysis-workflow.md"],
    "bug_draft": ["workflows/10-runtime-testcase-generation-workflow.md", "workflows/07-bug-draft-workflow.md"],
    "report_generation": ["workflows/10-runtime-testcase-generation-workflow.md", "workflows/08-report-generation-workflow.md"],
    "archive": ["workflows/10-runtime-testcase-generation-workflow.md", "workflows/09-archive-workflow.md"],
}

# 默认 fallback（无意图匹配时使用 testcase 工作流）
DEFAULT_WORKFLOW_FILES = [
    "workflows/10-runtime-testcase-generation-workflow.md",
    "workflows/02-testcase-generation-workflow.md",
]


def workflow_selector_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    state.record_node("workflow_selector_node")
    if state.errors:
        return state

    # 根据 intent 选择工作流文件
    if state.intent and state.intent in INTENT_WORKFLOW_FILES:
        state.workflow_files = list(INTENT_WORKFLOW_FILES[state.intent])
    else:
        state.workflow_files = list(DEFAULT_WORKFLOW_FILES)

    # 验证文件都存在
    for relative_path in state.workflow_files:
        if not (repo_root / relative_path).is_file():
            state.errors.append(f"缺少 Runtime 工作流文件: {relative_path}")
    return state
