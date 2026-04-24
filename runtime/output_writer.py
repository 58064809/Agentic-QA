from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from runtime.redaction import redact_text

SAFE_INTENT_NAMES = {
    "requirement_analysis": "requirement_analysis",
    "test_case_generation": "test_cases",
    "script_generation": "pytest_script",
    "test_workflow_execution": "test_workflow_execution",
    "test_execution": "pytest_execution",
    "result_analysis": "pytest_result_analysis",
    "log_analysis": "log_analysis",
}

OUTPUT_SUBDIRECTORIES = {
    "requirement_analysis": "requirement_analysis",
    "test_case_generation": "test_cases",
    "script_generation": "scripts",
    "test_workflow_execution": "test_execution",
    "test_execution": "test_reports",
    "result_analysis": "test_reports",
    "log_analysis": "log_analysis",
}


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _write_text(path: Path, content: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {
        "path": str(path),
        "relative_path": str(path),
        "bytes": path.stat().st_size,
    }


def save_assistant_output(
    workspace_root: Path,
    intent_name: str,
    formatted_output: str,
    skill_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir = workspace_root / "outputs" / OUTPUT_SUBDIRECTORIES.get(intent_name, intent_name)
    base_name = SAFE_INTENT_NAMES.get(intent_name, intent_name)
    timestamp = _timestamp()
    files: list[dict[str, Any]] = []

    markdown_path = output_dir / f"{timestamp}_{base_name}.md"
    redacted_output = redact_text(formatted_output)
    file_info = _write_text(markdown_path, redacted_output)
    file_info.update(
        {
            "kind": "markdown",
            "redacted": redacted_output != formatted_output,
            "relative_path": _safe_relative_to_root(markdown_path, workspace_root),
        }
    )
    files.append(file_info)

    if intent_name == "script_generation" and skill_result:
        script_content = skill_result.get("script_content", "")
        recommended_file_name = skill_result.get("recommended_file_name") or f"{timestamp}_{base_name}.py"
        if script_content:
            script_path = output_dir / recommended_file_name
            script_info = _write_text(script_path, script_content)
            script_info.update(
                {
                    "kind": "python",
                    "redacted": False,
                    "relative_path": _safe_relative_to_root(script_path, workspace_root),
                }
            )
            files.append(script_info)

    return {
        "output_dir": str(output_dir),
        "files": files,
    }


def _safe_relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
