from __future__ import annotations

import json
from pathlib import Path

import yaml

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


def _structured_payload(state: QAWorkflowState, key: str, markdown_path: str) -> dict[str, object]:
    artifact = next((item for item in state.artifacts if item.get("name") == key), {})
    return {
        "schema_version": "agentic-qa.artifact.v1",
        "name": key,
        "artifact_type": artifact.get("artifact_type", key),
        "status": state.review_status,
        "human_review_required": True,
        "prd_path": state.prd_path,
        "task_type": state.task_type,
        "markdown_path": markdown_path,
        "source_files": sorted(state.loaded_files.keys()),
        "quality_errors": list(state.quality_errors),
        "warnings": list(state.warnings),
    }


def _write_structured_companions(
    repo_root: Path,
    state: QAWorkflowState,
    key: str,
) -> None:
    markdown_path = state.output_paths[key]
    path = repo_root / Path(markdown_path)
    payload = _structured_payload(state, key, markdown_path)
    json_path = path.with_suffix(".json")
    yaml_path = path.with_suffix(".yml")
    if json_path.exists() or yaml_path.exists():
        raise FileExistsError(
            "目标结构化数据文件已存在，默认不覆盖: "
            + ", ".join(p.as_posix() for p in (json_path, yaml_path) if p.exists())
        )
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    yaml_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def mvp_artifact_writer_node(
    state: QAWorkflowState, repo_root: Path
) -> QAWorkflowState:
    state.record_node("mvp_artifact_writer_node")
    if state.errors or state.quality_errors:
        return state
    if state.review_status not in {"approved", "write_approved"}:
        state.errors.append("未获得 Runtime 写入授权，拒绝写入产物。")
        return state
    if state.dry_run:
        return state
    if not state.approve_write:
        state.errors.append("未显式传入 approve_write，拒绝写入。")
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

    existing_paths = []
    for key in keys:
        markdown_path = repo_root / Path(state.output_paths[key])
        companion_paths = [
            markdown_path,
            markdown_path.with_suffix(".json"),
            markdown_path.with_suffix(".yml"),
        ]
        existing_paths.extend(
            path.relative_to(repo_root).as_posix()
            for path in companion_paths
            if path.exists()
        )
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
            _write_structured_companions(repo_root, state, key)
    except FileExistsError as exc:
        state.errors.append(str(exc))
        return state

    state.wrote_file = True
    _mark_artifacts_written(state, set(keys))
    return state
