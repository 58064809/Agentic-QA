from __future__ import annotations

from pathlib import Path

from runtime.graph.nodes.mvp_context_loader import (
    TASK_ANALYSIS,
    TASK_MVP,
    TASK_TESTCASE_GENERATION,
)
from runtime.graph.state import QAWorkflowState
from runtime.tools.artifact_writer import write_new_text


def _artifact_keys_for_task(state: QAWorkflowState) -> list[str]:
    if state.task_type == TASK_ANALYSIS:
        return ["requirement_analysis"]
    if state.task_type == TASK_TESTCASE_GENERATION:
        return ["testcases"]
    if state.task_type == TASK_MVP:
        return ["requirement_analysis", "testcases"]
    return []


def _mark_artifacts_written(state: QAWorkflowState, keys: set[str]) -> None:
    updated = []
    for artifact in state.artifacts:
        next_artifact = dict(artifact)
        if next_artifact.get("name") in keys:
            next_artifact["wrote_file"] = True
        updated.append(next_artifact)
    state.artifacts = updated


def mvp_artifact_writer_node(
    state: QAWorkflowState, repo_root: Path
) -> QAWorkflowState:
    state.record_node("mvp_artifact_writer_node")
    if state.errors or state.quality_errors:
        return state
    if state.review_status != "approved":
        state.errors.append("人工审核未通过，拒绝写入产物。")
        return state
    if state.dry_run:
        return state
    if not state.approve_write:
        state.errors.append("未显式传入 --approve-write，拒绝写入。")
        return state

    keys = _artifact_keys_for_task(state)
    missing = [
        key
        for key in keys
        if not state.output_paths.get(key) or not state.draft_artifacts.get(key)
    ]
    if missing:
        state.errors.append(f"缺少产物内容或输出路径，拒绝写入: {', '.join(missing)}")
        return state

    existing_paths = [
        state.output_paths[key]
        for key in keys
        if (repo_root / Path(state.output_paths[key])).exists()
    ]
    if existing_paths:
        state.errors.append(
            "目标文件已存在，默认不覆盖；本次未写入任何产物: "
            + ", ".join(existing_paths)
        )
        return state

    try:
        for key in keys:
            write_new_text(
                repo_root / Path(state.output_paths[key]),
                state.draft_artifacts[key],
            )
    except FileExistsError as exc:
        state.errors.append(str(exc))
        return state

    state.wrote_file = True
    _mark_artifacts_written(state, set(keys))
    return state
