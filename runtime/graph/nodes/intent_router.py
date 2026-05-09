from __future__ import annotations

from runtime.graph.state import QAWorkflowState

TESTCASE_KEYWORDS = ("测试用例", "用例", "testcase", "test case", "生成用例", "设计用例")


def intent_router_node(state: QAWorkflowState) -> QAWorkflowState:
    state.record_node("intent_router_node")
    normalized_input = state.user_input.lower()
    if any(keyword in normalized_input for keyword in TESTCASE_KEYWORDS):
        state.intent = "testcase_generation"
        return state

    state.errors.append("当前 Runtime Skeleton 仅支持测试用例生成 dry-run。")
    return state
