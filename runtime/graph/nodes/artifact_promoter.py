from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from runtime.graph.state import QAWorkflowState
from runtime.workspace import (
    ARTIFACT_SPECS,
    PRDWorkspace,
    now_iso,
    read_yaml_mapping,
    write_yaml_mapping,
)

APPROVED_REVIEW_STATUSES = {"approved"}


def _artifact_keys_for_task(state: QAWorkflowState) -> list[str]:
    if state.task_type == "analysis":
        return ["requirement_analysis"]
    if state.task_type == "testcase_generation" or state.task_type is None:
        return ["testcases"]
    if state.task_type == "api_test_draft":
        return ["api_test_draft"]
    if state.task_type == "mvp_analysis_testcases":
        return ["requirement_analysis", "testcases"]
    return list(ARTIFACT_SPECS)


def _version_id(run_id: str | None) -> str:
    suffix = (run_id or "manual").replace("/", "-").replace("\\", "-")
    return f"v{now_iso().replace(':', '').replace('+0000', 'Z')}-{suffix}"


def _read_yaml_if_exists(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return read_yaml_mapping(path)


def _approved_artifact_keys(workspace: PRDWorkspace, run_id: str | None) -> list[str]:
    keys: list[str] = []
    for key in ARTIFACT_SPECS:
        review = _read_yaml_if_exists(workspace.review_path(key))
        if review.get("status") in APPROVED_REVIEW_STATUSES:
            review_run_id = review.get("run_id")
            if run_id and review_run_id and review_run_id != run_id:
                continue
            keys.append(key)
            continue
    return keys


def _extract_marked_preview(preview: str, key: str) -> str | None:
    pattern = re.compile(
        rf"<!--\s*artifact:start\s+{re.escape(key)}\s*-->\s*(.*?)\s*"
        rf"<!--\s*artifact:end\s+{re.escape(key)}\s*-->",
        re.DOTALL,
    )
    match = pattern.search(preview)
    if not match:
        return None
    return match.group(1).strip() + "\n"


def _extract_heading_preview(preview: str, key: str) -> str | None:
    titles = {
        "requirement_analysis": "需求分析候选",
        "testcases": "测试用例候选",
        "api_test_draft": "接口测试草稿候选",
        "qa_report": "QA 报告候选",
    }
    title = titles.get(key, key)
    lines = preview.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == f"## {title}":
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end]).strip() + "\n"


def _strip_candidate_section_heading(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].startswith("## ") and "候选" in lines[0]:
        return "\n".join(lines[1:]).lstrip() + "\n"
    return content


def _promoted_front_matter(
    content: str,
    *,
    key: str,
    version: str,
    promoted_at: str,
    run_id: str | None,
) -> str:
    body = content.strip() + "\n"
    metadata: dict[str, Any] = {}
    if body.startswith("---\n"):
        end = body.find("\n---\n", 4)
        if end != -1:
            parsed = yaml.safe_load(body[4:end]) or {}
            if isinstance(parsed, dict):
                metadata.update(parsed)
            body = body[end + len("\n---\n") :].lstrip()

    metadata["artifact_type"] = ARTIFACT_SPECS[key]["artifact_type"]
    metadata["status"] = "confirmed"
    metadata["human_review_required"] = False
    metadata["generated_by"] = metadata.get("generated_by") or "agentic-qa-runtime"
    metadata["promoted_from_run"] = run_id or ""
    metadata["current_version"] = version
    metadata["promoted_at"] = promoted_at
    front_matter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{front_matter}\n---\n\n{body}"


def _preview_content_for_key(preview: str, key: str, keys: list[str]) -> str:
    extracted = _extract_marked_preview(preview, key) or _extract_heading_preview(preview, key)
    if extracted:
        return _strip_candidate_section_heading(extracted)
    if len(keys) == 1:
        return preview.rstrip() + "\n"
    raise ValueError(f"artifact-preview.md 中未找到 {key} 对应的候选内容")


def _archive_existing_current(
    workspace: PRDWorkspace,
    key: str,
    *,
    version: str,
    promoted_at: str,
    run_id: str | None,
) -> dict[str, Any] | None:
    spec = ARTIFACT_SPECS[key]
    current_path = workspace.root / spec["current_path"]
    if not current_path.is_file():
        return None

    history_dir = workspace.root / Path(spec["history_index"]).parent
    history_dir.mkdir(parents=True, exist_ok=True)
    archived_path = history_dir / f"{version}.previous.md"
    shutil.copy2(current_path, archived_path)
    return {
        "version": version,
        "path": archived_path.relative_to(workspace.root).as_posix(),
        "source": spec["current_path"],
        "source_run_id": run_id or "",
        "archived_at": promoted_at,
    }


def _update_history_index(
    workspace: PRDWorkspace,
    key: str,
    *,
    version: str,
    promoted_at: str,
    run_id: str | None,
    archived_previous: dict[str, Any] | None,
) -> None:
    spec = ARTIFACT_SPECS[key]
    index_path = workspace.root / spec["history_index"]
    index = _read_yaml_if_exists(index_path)
    index.setdefault("artifact", spec["current_path"])
    index.setdefault("artifact_type", spec["artifact_type"])
    index["current_version"] = version
    versions = index.get("versions")
    if not isinstance(versions, list):
        versions = []
    entry: dict[str, Any] = {
        "version": version,
        "path": spec["current_path"],
        "source_run_id": run_id or "",
        "promoted_at": promoted_at,
    }
    if archived_previous:
        entry["archived_previous"] = archived_previous
    versions.append(entry)
    index["versions"] = versions
    write_yaml_mapping(index_path, index)


def _update_metadata_and_review(
    workspace: PRDWorkspace,
    key: str,
    *,
    version: str,
    promoted_at: str,
    run_id: str | None,
) -> None:
    spec = ARTIFACT_SPECS[key]
    metadata = _read_yaml_if_exists(workspace.metadata_path)
    metadata["updated_at"] = promoted_at
    metadata["last_updated_by"] = "runtime.artifact_promoter_node"
    metadata["status"] = "confirmed"
    runtime_summary = {
        "run_id": run_id or "",
        "thread_id": run_id or "",
        "task_type": "promote_artifacts",
        "review_status": "confirmed",
        "next_action": "",
        "run_status": "completed",
        "wrote_file": True,
        "updated_at": promoted_at,
    }
    metadata["last_runtime_run"] = runtime_summary
    runtime_runs = metadata.get("runtime_runs")
    if not isinstance(runtime_runs, list):
        runtime_runs = []
    if not runtime_runs or runtime_runs[-1].get("run_id") != runtime_summary["run_id"]:
        runtime_runs.append(runtime_summary)
    metadata["runtime_runs"] = runtime_runs
    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    entry = artifacts.get(key)
    if not isinstance(entry, dict):
        entry = {}
    entry["current_path"] = spec["current_path"]
    entry["current_version"] = version
    entry["history_index"] = spec["history_index"]
    entry["latest_run_id"] = run_id or ""
    entry["latest_preview_path"] = (
        workspace.artifact_preview_path(run_id).relative_to(workspace.root).as_posix()
        if run_id
        else ""
    )
    entry["status"] = "confirmed"
    artifacts[key] = entry
    metadata["artifacts"] = artifacts
    write_yaml_mapping(workspace.metadata_path, metadata)

    review_path = workspace.review_path(key)
    review = _read_yaml_if_exists(review_path)
    review.setdefault("artifact", spec["current_path"])
    review.setdefault("artifact_type", spec["artifact_type"])
    review["status"] = "confirmed"
    review["decision"] = "promoted"
    review["reviewed_at"] = review.get("reviewed_at") or promoted_at
    review["promoted_at"] = promoted_at
    review["promoted_run_id"] = run_id or ""
    review["current_version"] = version
    write_yaml_mapping(review_path, review)


def artifact_promoter_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    state.record_node("artifact_promoter_node")
    if state.errors or state.quality_errors:
        return state

    workspace = PRDWorkspace(repo_root / Path(state.prd_path))
    preview_path = workspace.artifact_preview_path(state.run_id)
    if not preview_path.is_file():
        state.errors.append(f"未找到候选产物预览: {preview_path.as_posix()}")
        return state

    task_keys = _artifact_keys_for_task(state)
    approved_keys = _approved_artifact_keys(workspace, state.run_id)
    target_keys = [key for key in task_keys if key in approved_keys]
    if not target_keys:
        state.errors.append("没有已 approved 的 review 记录，拒绝晋升正式产物。")
        return state

    preview = preview_path.read_text(encoding="utf-8")
    promoted_at = now_iso()
    version = _version_id(state.run_id)
    output_paths: dict[str, str] = {}

    try:
        for key in target_keys:
            content = _preview_content_for_key(preview, key, task_keys)
            content = _promoted_front_matter(
                content,
                key=key,
                version=version,
                promoted_at=promoted_at,
                run_id=state.run_id,
            )
            current_path = workspace.current_artifact_path(key)
            current_path.parent.mkdir(parents=True, exist_ok=True)
            archived_previous = _archive_existing_current(
                workspace,
                key,
                version=version,
                promoted_at=promoted_at,
                run_id=state.run_id,
            )
            current_path.write_text(content, encoding="utf-8")
            _update_history_index(
                workspace,
                key,
                version=version,
                promoted_at=promoted_at,
                run_id=state.run_id,
                archived_previous=archived_previous,
            )
            _update_metadata_and_review(
                workspace,
                key,
                version=version,
                promoted_at=promoted_at,
                run_id=state.run_id,
            )
            output_paths[key] = current_path.relative_to(repo_root).as_posix()
    except ValueError as exc:
        state.errors.append(str(exc))
        return state

    state.output_paths = output_paths
    state.output_path = next(iter(output_paths.values()), state.output_path)
    state.review_status = "confirmed"
    state.run_status = "completed"
    state.wrote_file = True
    state.warnings.append("已将候选产物晋升为正式产物: " + ", ".join(sorted(output_paths)))
    return state


def promote_artifacts(
    prd_path: Path | str,
    run_id: str,
    *,
    repo_root: Path,
    task_type: str = "mvp_analysis_testcases",
) -> QAWorkflowState:
    state = QAWorkflowState(
        user_input="promote_artifacts",
        prd_path=Path(prd_path).as_posix(),
        task_type=task_type,
        run_id=run_id,
        run_status="promoting",
    )
    return artifact_promoter_node(state, repo_root.resolve())
