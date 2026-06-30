from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

from runtime.graph.nodes.mvp_context_loader import (
    TASK_ANALYSIS,
    TASK_API_DISCOVERY_REPORT,
    TASK_API_TEST_DRAFT,
    TASK_MVP,
    TASK_TESTCASE_GENERATION,
    TASK_UI_TEST_DRAFT,
)
from runtime.graph.state import QAWorkflowState
from runtime.tools.artifact_writer import write_new_text
from runtime.workspace import combined_artifact_preview

RUNS_DIR_NAME = "runs"
LATEST_FILE = "latest.yml"
INDEX_FILE = "index.jsonl"


def _now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _artifact_keys_for_task(state: QAWorkflowState) -> list[str]:
    if state.task_type == TASK_ANALYSIS:
        return ["requirement_analysis"]
    if state.task_type == TASK_TESTCASE_GENERATION:
        return ["testcases"]
    if state.task_type == TASK_API_TEST_DRAFT:
        return ["api_test_draft"]
    if state.task_type == TASK_UI_TEST_DRAFT:
        return ["ui_test_draft"]
    if state.task_type == TASK_API_DISCOVERY_REPORT:
        return ["api_discovery_report"]
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


def _write_preview_companions(
    repo_root: Path,
    state: QAWorkflowState,
    keys: list[str],
    markdown_path: str,
) -> None:
    path = repo_root / Path(markdown_path)
    payload = {
        "schema_version": "agentic-qa.artifact-preview.v1",
        "status": state.review_status,
        "human_review_required": True,
        "prd_path": state.prd_path,
        "task_type": state.task_type,
        "markdown_path": markdown_path,
        "artifacts": [_structured_payload(state, key, markdown_path) for key in keys],
        "source_files": sorted(state.loaded_files.keys()),
        "quality_errors": list(state.quality_errors),
        "warnings": list(state.warnings),
    }
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


def _prd_root_from_output_path(repo_root: Path, output_path: str) -> Path | None:
    parts = Path(output_path).parts
    if RUNS_DIR_NAME not in parts:
        return None
    runs_index = parts.index(RUNS_DIR_NAME)
    if runs_index == 0:
        return None
    return (repo_root / Path(*parts[:runs_index])).resolve()


def _write_run_pointers(repo_root: Path, state: QAWorkflowState, keys: list[str]) -> None:
    first_output = next((state.output_paths.get(key) for key in keys), None)
    if not first_output:
        return
    prd_root = _prd_root_from_output_path(repo_root, first_output)
    if prd_root is None:
        return

    runs_dir = prd_root / RUNS_DIR_NAME
    runs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "agentic-qa.run-index.v1",
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "task_type": state.task_type,
        "prd_path": state.prd_path,
        "updated_at": _now_iso(),
        "output_paths": {key: state.output_paths[key] for key in keys},
        "review_status": state.review_status,
        "quality_errors": list(state.quality_errors),
        "warnings": list(state.warnings),
    }

    (runs_dir / LATEST_FILE).write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    with (runs_dir / INDEX_FILE).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _candidate_markdown_path(path: Path, run_id: str | None) -> Path:
    suffix = run_id or "runtime"
    return path.with_name(f"{path.stem}.{suffix}{path.suffix}")


def _next_available_markdown_path(path: Path, run_id: str | None) -> Path:
    candidate = _candidate_markdown_path(path, run_id)
    if not any(
        companion.exists()
        for companion in (candidate, candidate.with_suffix(".json"), candidate.with_suffix(".yml"))
    ):
        return candidate

    index = 2
    while True:
        indexed = candidate.with_name(f"{candidate.stem}-{index}{candidate.suffix}")
        if not any(
            companion.exists()
            for companion in (indexed, indexed.with_suffix(".json"), indexed.with_suffix(".yml"))
        ):
            return indexed
        index += 1


def _remap_existing_output_paths(
    repo_root: Path,
    state: QAWorkflowState,
    keys: list[str],
) -> None:
    remapped: dict[str, str] = {}
    for key in keys:
        output_path = state.output_paths[key]
        markdown_path = repo_root / Path(output_path)
        companion_paths = [
            markdown_path,
            markdown_path.with_suffix(".json"),
            markdown_path.with_suffix(".yml"),
        ]
        if not any(path.exists() for path in companion_paths):
            continue

        candidate = _next_available_markdown_path(markdown_path, state.run_id)
        relative_candidate = candidate.relative_to(repo_root).as_posix()
        state.output_paths[key] = relative_candidate
        remapped[output_path] = relative_candidate

    if not remapped:
        return

    updated = []
    for artifact in state.artifacts:
        next_artifact = dict(artifact)
        artifact_path = next_artifact.get("output_path")
        if artifact_path in remapped:
            next_artifact["output_path"] = remapped[artifact_path]
        updated.append(next_artifact)
    state.artifacts = updated

    if state.output_path in remapped:
        state.output_path = remapped[state.output_path]

    state.warnings.append(
        "检测到目标草稿已存在，已改写入本次 run 候选文件: "
        + ", ".join(f"{source} -> {target}" for source, target in sorted(remapped.items()))
    )


def artifact_preview_writer_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    state.record_node("artifact_preview_writer_node")
    if state.errors or state.quality_errors:
        return state
    if state.review_status == "not_started":
        state.review_status = "needs_human_review"
        state.run_status = "interrupted"
        state.next_action = "wait_for_review"
    if state.review_status not in {"needs_human_review", "approved", "write_approved"}:
        state.errors.append("未进入 Review Gate，拒绝写入候选产物。")
        return state

    keys = _artifact_keys_for_task(state)
    if state.wrote_file:
        paths = [
            repo_root / Path(state.output_paths[key]) for key in keys if state.output_paths.get(key)
        ]
        if paths and all(path.exists() for path in paths):
            return state

    missing = [
        key for key in keys if not state.output_paths.get(key) or not state.draft_artifacts.get(key)
    ]
    if missing:
        state.errors.append(f"缺少产物内容或输出路径，拒绝写入: {', '.join(missing)}")
        return state

    _remap_existing_output_paths(repo_root, state, keys)

    try:
        unique_paths = {state.output_paths[key] for key in keys}
        if len(unique_paths) == 1:
            markdown_path = next(iter(unique_paths))
            preview = combined_artifact_preview({key: state.draft_artifacts[key] for key in keys})
            write_new_text(repo_root / Path(markdown_path), preview)
            _write_preview_companions(repo_root, state, keys, markdown_path)
        else:
            for key in keys:
                write_new_text(
                    repo_root / Path(state.output_paths[key]),
                    state.draft_artifacts[key],
                )
                _write_structured_companions(repo_root, state, key)
        _write_run_pointers(repo_root, state, keys)
    except FileExistsError as exc:
        state.errors.append(str(exc))
        return state

    state.wrote_file = True
    _mark_artifacts_written(state, set(keys))
    return state
