from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from runtime.records.run_id import generate_run_id
from runtime.schemas.runtime_result import RuntimeResult

DRAFT_PREVIEW_CHARS = 300


def now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def relative_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def result_to_summary(result: RuntimeResult, created_at: str) -> dict[str, object]:
    draft_artifact_previews = {
        name: content[:DRAFT_PREVIEW_CHARS]
        for name, content in result.draft_artifacts.items()
    }
    return {
        "run_id": result.run_id,
        "created_at": created_at,
        "success": result.success,
        "orchestration": result.orchestration,
        "mode": "approve-write" if result.approve_write else "dry-run",
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
        "llm": result.llm,
        "requirement_normalization": result.requirement_normalization,
        "prototype_notes": result.prototype_notes,
        "errors": result.errors,
        "warnings": result.warnings,
        "quality_errors": result.quality_errors,
        "draft_artifact_preview": (result.draft_artifact or "")[:DRAFT_PREVIEW_CHARS],
        "draft_artifact_previews": draft_artifact_previews,
    }


def format_list(items: list[str], empty_text: str = "无") -> str:
    if not items:
        return f"- {empty_text}"
    return "\n".join(f"- {item}" for item in items)


def render_markdown_summary(summary: dict[str, object]) -> str:
    mode = summary["mode"]
    return f"""# Runtime 运行记录

## 基本信息

- Run ID：{summary["run_id"]}
- 时间：{summary["created_at"]}
- 模式：{mode}
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

## 原型图说明

- loaded：{dict(summary["prototype_notes"]).get("loaded")}
- path：{dict(summary["prototype_notes"]).get("path")}
- requirement_has_images：{dict(summary["prototype_notes"]).get("requirement_has_images")}
- warning：{dict(summary["prototype_notes"]).get("warning")}

## 文件与产物

- 输出路径：{summary["output_path"] or "未生成"}
- 是否写入：{"是" if summary["wrote_file"] else "否"}

## 加载文件

{format_list(list(summary["loaded_files"]))}

## 审核状态

- review_status：{summary["review_status"]}

## 错误与警告

### errors

{format_list(list(summary["errors"]))}

### warnings

{format_list(list(summary["warnings"]))}

### quality_errors

{format_list(list(summary["quality_errors"]))}
"""


def record_runtime_result(result: RuntimeResult, repo_root: Path) -> RuntimeResult:
    run_id = result.run_id or generate_run_id()
    run_record_dir = repo_root / ".runtime" / "runs" / run_id
    summary_json = run_record_dir / "run-summary.json"
    summary_md = run_record_dir / "run-summary.md"
    created_at = now_iso()

    relative_dir = relative_to_repo(run_record_dir, repo_root)
    relative_json = relative_to_repo(summary_json, repo_root)
    relative_md = relative_to_repo(summary_md, repo_root)
    result_with_paths = replace(
        result,
        run_id=run_id,
        run_record_dir=relative_dir,
        run_summary_json=relative_json,
        run_summary_md=relative_md,
    )

    try:
        run_record_dir.mkdir(parents=True, exist_ok=False)
        summary = result_to_summary(result_with_paths, created_at)
        summary_json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        summary_md.write_text(render_markdown_summary(summary), encoding="utf-8")
    except OSError as exc:
        errors = [*result_with_paths.errors, f"运行记录写入失败: {exc}"]
        return replace(result_with_paths, success=False, errors=errors)

    return result_with_paths
