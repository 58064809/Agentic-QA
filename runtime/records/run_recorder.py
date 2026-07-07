from __future__ import annotations

import json
import os
import pickle
import threading
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from runtime.records.run_id import generate_run_id
from runtime.schemas.runtime_result import RuntimeResult

DRAFT_PREVIEW_CHARS = 300
CHECKPOINTER_FILE = "checkpointer.pkl"
CHECKPOINT_MANIFEST_FILE = "checkpoint-manifest.json"
GRAPH_STATE_FILE = "graph-state.json"
RUN_STATE_FILE = "run-state.json"
REVIEW_EVENTS_FILE = "review-events.jsonl"
RAG_TRACE_FILE = "rag.json"
DEFAULT_POSTGRES_DSN_ENV = "AGENTIC_QA_CHECKPOINT_POSTGRES_DSN"


def now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def relative_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def run_record_dir_for(repo_root: Path, run_id: str) -> Path:
    return repo_root / ".runtime" / "runs" / run_id


def review_events_path_for(run_record_dir: Path) -> Path:
    return run_record_dir / REVIEW_EVENTS_FILE


def create_run_identity(run_id: str | None = None) -> tuple[str, str]:
    next_run_id = run_id or generate_run_id()
    return next_run_id, next_run_id


def sanitize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_for_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [sanitize_for_json(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if hasattr(value, "value") and hasattr(value, "id"):
        return {
            "type": value.__class__.__name__,
            "id": str(value.id),
            "value": sanitize_for_json(value.value),
        }
    return repr(value)


def plain_mapping(value: Any) -> Any:
    if isinstance(value, defaultdict | dict):
        return {key: plain_mapping(item) for key, item in value.items()}
    return value


def nested_defaultdict(value: dict) -> defaultdict:
    outer: defaultdict = defaultdict(lambda: defaultdict(dict))
    for thread_id, namespaces in value.items():
        outer[thread_id] = defaultdict(dict)
        for namespace, checkpoints in namespaces.items():
            outer[thread_id][namespace] = dict(checkpoints)
    return outer


def _checkpointer_payload(checkpointer: Any) -> dict[str, Any]:
    return {
        "storage": plain_mapping(checkpointer.storage),
        "writes": plain_mapping(checkpointer.writes),
        "blobs": dict(checkpointer.blobs),
    }


def _restore_checkpointer_payload(checkpointer: MemorySaver, payload: dict[str, Any]) -> None:
    checkpointer.storage = nested_defaultdict(payload.get("storage", {}))
    checkpointer.writes = defaultdict(dict, payload.get("writes", {}))
    checkpointer.blobs = dict(payload.get("blobs", {}))


def _checkpoint_count(checkpointer: Any) -> int:
    storage = plain_mapping(getattr(checkpointer, "storage", {}))
    return sum(
        len(checkpoints)
        for namespaces in storage.values()
        if isinstance(namespaces, dict)
        for checkpoints in namespaces.values()
        if isinstance(checkpoints, dict)
    )


def _checkpointer_storage(checkpointer: Any) -> str:
    storage = getattr(checkpointer, "_agentic_qa_checkpoint_storage", "")
    if storage:
        return str(storage)
    if hasattr(checkpointer, "storage") and hasattr(checkpointer, "writes"):
        return "file_pickle"
    module = checkpointer.__class__.__module__
    if "postgres" in module:
        return "postgres"
    return "unknown"


def write_checkpoint_manifest(checkpointer: Any, run_record_dir: Path) -> Path:
    storage = _checkpointer_storage(checkpointer)
    manifest = {
        "schema_version": "v1",
        "checkpointer_type": checkpointer.__class__.__name__,
        "storage": storage,
        "checkpoint_file": CHECKPOINTER_FILE if storage == "file_pickle" else None,
        "checkpoint_count": _checkpoint_count(checkpointer) if storage == "file_pickle" else None,
        "dsn_env": getattr(checkpointer, "_agentic_qa_postgres_dsn_env", None),
        "setup": getattr(checkpointer, "_agentic_qa_postgres_setup", None),
        "updated_at": now_iso(),
    }
    path = run_record_dir / CHECKPOINT_MANIFEST_FILE
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def save_checkpointer(checkpointer: Any, run_record_dir: Path) -> Path:
    storage = _checkpointer_storage(checkpointer)
    if storage != "file_pickle":
        return write_checkpoint_manifest(checkpointer, run_record_dir)
    payload = {
        "schema_version": "v1",
        "payload": _checkpointer_payload(checkpointer),
    }
    path = run_record_dir / CHECKPOINTER_FILE
    run_record_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    tmp_path.write_bytes(pickle.dumps(payload))
    tmp_path.replace(path)
    write_checkpoint_manifest(checkpointer, run_record_dir)
    return path


class PersistedMemorySaver(MemorySaver):
    """MemorySaver that mirrors checkpoints to the run record directory.

    The current dependency set does not include LangGraph's sqlite checkpointer package.
    This adapter keeps the existing MemorySaver behavior while persisting after every
    checkpoint write so interrupted or failed runs can be resumed from disk.
    """

    def __init__(self, run_record_dir: Path) -> None:
        super().__init__()
        self.run_record_dir = run_record_dir
        self._persist_lock = threading.RLock()
        path = run_record_dir / CHECKPOINTER_FILE
        if path.is_file():
            payload = pickle.loads(path.read_bytes())
            data = payload.get("payload", payload) if isinstance(payload, dict) else {}
            if isinstance(data, dict):
                _restore_checkpointer_payload(self, data)

    def _persist(self) -> None:
        with self._persist_lock:
            save_checkpointer(self, self.run_record_dir)

    def put(self, config, checkpoint, metadata, new_versions):
        next_config = super().put(config, checkpoint, metadata, new_versions)
        self._persist()
        return next_config

    def put_writes(self, config, writes, task_id, task_path="") -> None:
        super().put_writes(config, writes, task_id, task_path)
        self._persist()

    def delete_thread(self, thread_id: str) -> None:
        super().delete_thread(thread_id)
        self._persist()

    def delete_for_runs(self, run_ids) -> None:
        super().delete_for_runs(run_ids)
        self._persist()


def _create_postgres_checkpointer(
    *,
    dsn_env: str = DEFAULT_POSTGRES_DSN_ENV,
    setup: bool = True,
) -> Any:
    dsn = os.getenv(dsn_env, "").strip()
    if not dsn:
        raise RuntimeError(f"未设置 PostgreSQL checkpointer 连接串环境变量: {dsn_env}")
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError as exc:
        raise RuntimeError(
            "缺少 PostgreSQL checkpointer 依赖，请安装 langgraph-checkpoint-postgres "
            "和 psycopg[binary]。"
        ) from exc
    context_manager = PostgresSaver.from_conn_string(dsn)
    checkpointer = context_manager.__enter__()
    checkpointer._agentic_qa_context_manager = context_manager
    checkpointer._agentic_qa_checkpoint_storage = "postgres"
    checkpointer._agentic_qa_postgres_dsn_env = dsn_env
    checkpointer._agentic_qa_postgres_setup = setup
    if setup:
        checkpointer.setup()
    return checkpointer


def create_checkpointer(
    run_record_dir: Path | None = None,
    *,
    storage: str = "postgres",
    postgres_dsn_env: str = DEFAULT_POSTGRES_DSN_ENV,
    postgres_setup: bool = True,
) -> Any:
    normalized_storage = storage.strip().lower()
    if normalized_storage in {"postgres", "postgresql"}:
        return _create_postgres_checkpointer(
            dsn_env=postgres_dsn_env,
            setup=postgres_setup,
        )
    if run_record_dir is None:
        return MemorySaver()
    run_record_dir.mkdir(parents=True, exist_ok=True)
    return PersistedMemorySaver(run_record_dir)


def load_checkpointer(
    run_record_dir: Path,
    *,
    storage: str = "postgres",
    postgres_dsn_env: str = DEFAULT_POSTGRES_DSN_ENV,
    postgres_setup: bool = True,
) -> Any:
    normalized_storage = storage.strip().lower()
    if normalized_storage in {"postgres", "postgresql"}:
        return _create_postgres_checkpointer(
            dsn_env=postgres_dsn_env,
            setup=postgres_setup,
        )
    return PersistedMemorySaver(run_record_dir)


def close_checkpointer(checkpointer: Any) -> None:
    context_manager = getattr(checkpointer, "_agentic_qa_context_manager", None)
    if context_manager is not None:
        context_manager.__exit__(None, None, None)


def write_runtime_state(
    *,
    result: RuntimeResult,
    repo_root: Path,
    run_record_dir: Path,
    graph_state: dict[str, Any] | None,
    created_at: str,
) -> None:
    state_payload = {
        "run_id": result.run_id,
        "thread_id": result.thread_id,
        "run_status": result.run_status,
        "created_at": created_at,
        "updated_at": now_iso(),
        "result": sanitize_for_json(result.__dict__),
        "graph_state": sanitize_for_json(graph_state or {}),
        "review_events": read_review_events(run_record_dir),
    }
    (run_record_dir / RUN_STATE_FILE).write_text(
        json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_record_dir / GRAPH_STATE_FILE).write_text(
        json.dumps(sanitize_for_json(graph_state or {}), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_review_events(run_record_dir: Path) -> list[dict[str, Any]]:
    path = review_events_path_for(run_record_dir)
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def read_checkpoint_manifest(run_record_dir: Path) -> dict[str, Any]:
    path = run_record_dir / CHECKPOINT_MANIFEST_FILE
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def append_review_event(
    result: RuntimeResult,
    repo_root: Path,
    *,
    action: str,
    reviewed_by: str,
    review_notes: str | None,
    previous_status: str,
    previous_run_status: str | None = None,
) -> Path:
    if not result.run_id:
        raise ValueError("缺少 run_id，无法记录人工审核事件。")

    run_record_dir = run_record_dir_for(repo_root, result.run_id)
    run_record_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "run_id": result.run_id,
        "thread_id": result.thread_id,
        "action": action,
        "reviewed_by": reviewed_by,
        "review_notes": review_notes,
        "created_at": now_iso(),
        "previous_status": previous_status,
        "previous_run_status": previous_run_status,
        "next_status": result.review_status,
        "next_action": result.next_action,
        "next_run_status": result.run_status,
        "wrote_file": result.wrote_file,
        "output_path": result.output_path,
        "output_paths": result.output_paths,
        "errors": result.errors,
        "warnings": result.warnings,
    }
    path = review_events_path_for(run_record_dir)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


def result_to_summary(
    result: RuntimeResult,
    created_at: str,
    *,
    review_events: list[dict[str, Any]] | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, object]:
    draft_artifact_previews = {
        name: content[:DRAFT_PREVIEW_CHARS] for name, content in result.draft_artifacts.items()
    }
    return {
        "run_id": result.run_id,
        "thread_id": result.thread_id,
        "created_at": created_at,
        "success": result.success,
        "run_status": result.run_status,
        "orchestration": result.orchestration,
        "mode": "debug-preview-write" if result.debug_approve_preview_write else "dry-run",
        "task_type": result.task_type,
        "user_input": result.user_input,
        "prd_path": result.prd_path,
        "intent": result.intent,
        "workflow_files": result.workflow_files,
        "loaded_files": sorted(result.loaded_files),
        "executed_nodes": result.executed_nodes,
        "output_path": result.output_path,
        "output_paths": result.output_paths,
        "artifacts": result.artifacts,
        "wrote_file": result.wrote_file,
        "review_status": result.review_status,
        "next_action": result.next_action,
        "human_review": result.human_review,
        "review_events": review_events or [],
        "checkpoint": checkpoint or {},
        "llm": result.llm,
        "requirement_normalization": result.requirement_normalization,
        "image_detection": result.prototype_notes,
        "prototype_notes": result.prototype_notes,
        "errors": result.errors,
        "warnings": result.warnings,
        "quality_errors": result.quality_errors,
        "rag_retrievals": result.rag_retrievals,
        "draft_artifact_preview": (result.draft_artifact or "")[:DRAFT_PREVIEW_CHARS],
        "draft_artifact_previews": draft_artifact_previews,
    }


def format_list(items: list[str], empty_text: str = "无") -> str:
    if not items:
        return f"- {empty_text}"
    return "\n".join(f"- {item}" for item in items)


def format_mapping(mapping: dict[str, str], empty_text: str = "无") -> str:
    if not mapping:
        return f"- {empty_text}"
    return "\n".join(f"- {key}：{value}" for key, value in sorted(mapping.items()))


def format_artifacts(artifacts: list[dict[str, object]], empty_text: str = "无") -> str:
    if not artifacts:
        return f"- {empty_text}"
    lines = []
    for artifact in artifacts:
        name = artifact.get("name") or "unknown"
        output_path = artifact.get("output_path") or "未生成"
        wrote_file = "是" if artifact.get("wrote_file") else "否"
        status = artifact.get("status") or "unknown"
        lines.append(f"- {name}：{output_path}；wrote_file={wrote_file}；status={status}")
    return "\n".join(lines)


def render_markdown_summary(summary: dict[str, object]) -> str:
    mode = summary["mode"]
    return f"""# Runtime 运行记录

## 基本信息

- Run ID：{summary["run_id"]}
- Thread ID：{summary["thread_id"]}
- 时间：{summary["created_at"]}
- 模式：{mode}
- 运行状态：{summary["run_status"]}
- 编排方式：{summary["orchestration"]}
- PRD：{summary["prd_path"]}
- 意图：{summary["intent"] or "未识别"}
- 任务类型：{summary["task_type"] or "未记录"}
- 成功：{summary["success"]}

## 节点轨迹

{format_list(list(summary["executed_nodes"]))}

## LLM

- enabled：{dict(summary["llm"]).get("enabled")}
- used：{dict(summary["llm"]).get("used")}
- provider：{dict(summary["llm"]).get("provider")}
- base_url：{dict(summary["llm"]).get("base_url")}
- model：{dict(summary["llm"]).get("model")}
- calls：{dict(summary["llm"]).get("calls")}

## 需求文档归一化

- performed：{dict(summary["requirement_normalization"]).get("performed")}
- source_path：{dict(summary["requirement_normalization"]).get("source_path")}
- output_path：{dict(summary["requirement_normalization"]).get("output_path")}
- source_type：{dict(summary["requirement_normalization"]).get("source_type")}
- skipped_reason：{dict(summary["requirement_normalization"]).get("skipped_reason")}

## 图片检测

- requirement_has_images：{dict(summary["image_detection"]).get("requirement_has_images")}
- warning：{dict(summary["image_detection"]).get("warning")}
- prototype_notes_loaded：{dict(summary["image_detection"]).get("loaded")}
- prototype_notes_path：{dict(summary["image_detection"]).get("path")}

## 文件与产物

- 输出路径：{summary["output_path"] or "未生成"}
- 多产物输出路径：
{format_mapping(dict(summary["output_paths"]))}
- 是否写入：{"是" if summary["wrote_file"] else "否"}
- 产物清单：
{format_artifacts(list(summary["artifacts"]))}

## 加载文件

{format_list(list(summary["loaded_files"]))}

## 审核状态

- review_status：{summary["review_status"]}
- next_action：{summary["next_action"] or "未设置"}
- human_review：{json.dumps(summary["human_review"], ensure_ascii=False)}
- review_events：{len(list(summary["review_events"]))}
- checkpoint：{json.dumps(summary["checkpoint"], ensure_ascii=False)}

## 错误与警告

### errors

{format_list(list(summary["errors"]))}

### warnings

{format_list(list(summary["warnings"]))}

### quality_errors

{format_list(list(summary["quality_errors"]))}
"""


def write_rag_trace(result: RuntimeResult, run_record_dir: Path) -> None:
    payload = {
        "run_id": result.run_id,
        "thread_id": result.thread_id,
        "retrievals": result.rag_retrievals,
    }
    (run_record_dir / RAG_TRACE_FILE).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def record_runtime_result(
    result: RuntimeResult,
    repo_root: Path,
    *,
    graph_state: dict[str, Any] | None = None,
    checkpointer: Any | None = None,
) -> RuntimeResult:
    run_id = result.run_id or generate_run_id()
    thread_id = result.thread_id or run_id
    run_record_dir = run_record_dir_for(repo_root, run_id)
    summary_json = run_record_dir / "run-summary.json"
    summary_md = run_record_dir / "run-summary.md"
    created_at = now_iso()

    relative_dir = relative_to_repo(run_record_dir, repo_root)
    relative_json = relative_to_repo(summary_json, repo_root)
    relative_md = relative_to_repo(summary_md, repo_root)
    result_with_paths = replace(
        result,
        run_id=run_id,
        thread_id=thread_id,
        run_record_dir=relative_dir,
        run_summary_json=relative_json,
        run_summary_md=relative_md,
    )

    try:
        run_record_dir.mkdir(parents=True, exist_ok=True)
        if checkpointer is not None:
            save_checkpointer(checkpointer, run_record_dir)
        summary = result_to_summary(
            result_with_paths,
            created_at,
            review_events=read_review_events(run_record_dir),
            checkpoint=read_checkpoint_manifest(run_record_dir),
        )
        summary_json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        summary_md.write_text(render_markdown_summary(summary), encoding="utf-8")
        write_rag_trace(result_with_paths, run_record_dir)
        write_runtime_state(
            result=result_with_paths,
            repo_root=repo_root,
            run_record_dir=run_record_dir,
            graph_state=graph_state,
            created_at=created_at,
        )
    except OSError as exc:
        errors = [*result_with_paths.errors, f"运行记录写入失败: {exc}"]
        return replace(result_with_paths, success=False, errors=errors)

    return result_with_paths
