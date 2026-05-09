from __future__ import annotations

from runtime.graph.state import QAWorkflowState


def metadata_update_node(state: QAWorkflowState) -> QAWorkflowState:
    state.record_node("metadata_update_node")
    if state.errors or state.quality_errors:
        return state

    state.warnings.append("metadata.yml 更新将在后续 Runtime 持久化任务中补充。")
    return state
