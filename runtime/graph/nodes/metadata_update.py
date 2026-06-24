from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from runtime.graph.state import QAWorkflowState
from runtime.workspace import ARTIFACT_SPECS, PRDWorkspace


def _now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _target_review_gate_names(state: QAWorkflowState) -> set[str]:
    if state.task_type == "analysis":
        return {"需求分析审核"}
    if state.task_type == "testcase_generation" or state.task_type is None:
        return {"测试用例审核"}
    if state.task_type == "mvp_analysis_testcases":
        return {"需求分析审核", "测试用例审核"}
    return set()


def _read_metadata(metadata_path: Path) -> dict[str, Any]:
    if not metadata_path.is_file():
        return {}
    with metadata_path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(data, stream, allow_unicode=True, sort_keys=False)


def _runtime_run_summary(state: QAWorkflowState, updated_at: str) -> dict[str, Any]:
    return {
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "task_type": state.task_type or "testcase_generation",
        "review_status": state.review_status,
        "next_action": state.next_action,
        "run_status": state.run_status,
        "wrote_file": state.wrote_file,
        "output_path": state.output_path,
        "output_paths": dict(state.output_paths),
        "reviewed_by": state.human_review.get("reviewed_by"),
        "review_notes": state.human_review.get("review_notes"),
        "updated_at": updated_at,
    }


def metadata_update_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    state.record_node("metadata_update_node")
    if state.errors or state.quality_errors:
        return state

    if not state.wrote_file:
        state.warnings.append("metadata.yml 未更新：本次 Runtime 未写入产物。")
        return state

    workspace = PRDWorkspace(repo_root / Path(state.prd_path))
    metadata_path = workspace.metadata_path
    if not metadata_path.is_file():
        state.warnings.append(f"metadata.yml 不存在，跳过 Runtime 写入记录: {metadata_path}")
        return state

    updated_at = _now_iso()
    metadata = _read_metadata(metadata_path)
    metadata["last_runtime_run"] = _runtime_run_summary(state, updated_at)
    runtime_runs = metadata.get("runtime_runs")
    if not isinstance(runtime_runs, list):
        runtime_runs = []
    runtime_runs.append(metadata["last_runtime_run"])
    metadata["runtime_runs"] = runtime_runs
    metadata["last_updated_by"] = "runtime.metadata_update_node"
    metadata["updated_at"] = updated_at
    if metadata.get("status") != "archived":
        metadata["status"] = (
            "approved" if state.review_status == "approved" else "needs_human_review"
        )

    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    for artifact in state.artifacts:
        name = artifact.get("name")
        if not isinstance(name, str) or name not in ARTIFACT_SPECS:
            continue
        entry = artifacts.get(name)
        if not isinstance(entry, dict):
            entry = {}
        spec = ARTIFACT_SPECS[name]
        entry.setdefault("current_path", spec["current_path"])
        entry.setdefault("current_version", "")
        entry.setdefault("history_index", spec["history_index"])
        entry["latest_run_id"] = state.run_id or ""
        entry["latest_preview_path"] = artifact.get("output_path") or state.output_path
        entry["status"] = "approved" if state.review_status == "approved" else "needs_human_review"
        artifacts[name] = entry

        review_path = workspace.review_path(name)
        review_record = _read_metadata(review_path)
        review_record.setdefault("artifact", spec["current_path"])
        review_record.setdefault("artifact_type", spec["artifact_type"])
        if state.review_status == "approved":
            review_record["status"] = "approved"
            review_record["decision"] = "approve"
            review_record["reviewed_at"] = updated_at
            review_record["reviewer"] = state.human_review.get("reviewed_by") or ""
            review_record["comments"] = [state.human_review.get("review_notes") or ""]
            review_record["next_action"] = "promote"
        else:
            review_record["status"] = "needs_human_review"
            review_record["decision"] = ""
            review_record["reviewed_at"] = None
            review_record["next_action"] = ""
        review_record["run_id"] = state.run_id or ""
        review_record["source_message"] = state.user_input
        _write_yaml(review_path, review_record)
    metadata["artifacts"] = artifacts

    target_gate_names = _target_review_gate_names(state)
    review_gates = metadata.get("review_gates")
    if isinstance(review_gates, list):
        for gate in review_gates:
            if not isinstance(gate, dict):
                continue
            if gate.get("name") in target_gate_names:
                gate["status"] = (
                    "approved" if state.review_status == "approved" else "needs_human_review"
                )
                gate["last_runtime_run"] = state.run_id
                gate["runtime_review_status"] = state.review_status
                gate["runtime_next_action"] = state.next_action
                gate["runtime_reviewed_by"] = state.human_review.get("reviewed_by")
                gate["updated_at"] = updated_at

    _write_yaml(metadata_path, metadata)
    state.warnings.append("metadata.yml 已记录 Runtime 写入和审批状态。")
    return state
