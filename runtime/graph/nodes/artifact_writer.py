"""LEGACY ONLY: old langgraph_app artifact writer.

Current runtime writes candidate previews through artifact_preview_writer and promotes
formal artifacts through the deterministic artifact_promoter path.
"""

from __future__ import annotations

from pathlib import Path

from runtime.graph.state import QAWorkflowState
from runtime.tools.artifact_writer import write_new_text


def artifact_writer_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    state.record_node("artifact_writer_node")
    if state.errors or state.quality_errors:
        return state
    if state.review_status not in {"approved", "write_approved"}:
        state.errors.append("未获得 Runtime 写入授权，拒绝写入产物。")
        return state
    if state.dry_run:
        return state
    if not state.approve_write:
        state.errors.append("未显式设置 approve_write 状态字段，拒绝写入。")
        return state
    if not state.output_path or not state.draft_artifact:
        state.errors.append("缺少输出路径或草稿内容，拒绝写入。")
        return state

    try:
        write_new_text(repo_root / Path(state.output_path), state.draft_artifact)
    except FileExistsError as exc:
        state.errors.append(str(exc))
        return state

    state.wrote_file = True
    return state
