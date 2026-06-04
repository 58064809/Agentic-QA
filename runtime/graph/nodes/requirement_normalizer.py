from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.graph.nodes.context_loader import resolve_prd_path
from runtime.graph.state import QAWorkflowState
from runtime.tools.artifact_writer import ensure_within_directory
from runtime.tools.document_converter import convert_requirement_to_markdown

SUPPORTED_REQUIREMENT_SOURCES = [
    "input/requirement.md",
    "input/requirement.docx",
    "input/requirement.pdf",
    "input/requirement.txt",
    "input/requirement.html",
    "input/requirement.htm",
    "input/requirement.rtf",
    "input/需求.md",
    "input/需求.docx",
    "input/需求.pdf",
    "input/需求.txt",
    "input/需求.html",
    "input/需求.htm",
]


def default_requirement_normalization() -> dict[str, Any]:
    return {
        "performed": False,
        "source_path": None,
        "output_path": None,
        "source_type": None,
        "skipped_reason": None,
    }


def _relative(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _set_normalization(
    state: QAWorkflowState,
    *,
    performed: bool,
    source_path: Path | None,
    output_path: Path | None,
    source_type: str | None,
    skipped_reason: str | None,
    repo_root: Path,
) -> None:
    state.requirement_normalization = {
        "performed": performed,
        "source_path": _relative(source_path, repo_root) if source_path else None,
        "output_path": _relative(output_path, repo_root) if output_path else None,
        "source_type": source_type,
        "skipped_reason": skipped_reason,
    }


def _candidate_sources(prd_path: Path) -> list[Path]:
    return [prd_path / filename for filename in SUPPORTED_REQUIREMENT_SOURCES]


def normalize_requirement_document(
    state: QAWorkflowState,
    repo_root: Path,
) -> QAWorkflowState:
    state.record_node("requirement_normalizer_node")
    if state.errors:
        return state

    prd_path = resolve_prd_path(repo_root, state.prd_path)
    if not prd_path.is_dir():
        state.errors.append(f"PRD 工作区不存在: {state.prd_path}")
        return state
    if not ensure_within_directory(prd_path, repo_root / "prd"):
        state.errors.append(f"PRD 工作区必须位于 prd/ 下: {state.prd_path}")
        return state

    requirement_md = prd_path / "input/requirement.md"
    if requirement_md.is_file():
        _set_normalization(
            state,
            performed=False,
            source_path=requirement_md,
            output_path=requirement_md,
            source_type="markdown",
            skipped_reason="input/requirement.md already exists",
            repo_root=repo_root,
        )
        return state

    existing_sources = [
        source
        for source in _candidate_sources(prd_path)
        if source != requirement_md and source.is_file()
    ]
    if not existing_sources:
        _set_normalization(
            state,
            performed=False,
            source_path=None,
            output_path=requirement_md,
            source_type=None,
            skipped_reason="no supported requirement source found",
            repo_root=repo_root,
        )
        supported = ", ".join(SUPPORTED_REQUIREMENT_SOURCES)
        state.errors.append(
            f"未找到需求源文件，请在目标 PRD 工作区提供以下文件之一: {supported}"
        )
        return state

    selected_source = existing_sources[0]
    if len(existing_sources) > 1:
        other_sources = ", ".join(_relative(path, repo_root) for path in existing_sources[1:])
        state.warnings.append(
            f"发现多个需求源文件，按优先级选择 {_relative(selected_source, repo_root)}；"
            f"未转换: {other_sources}"
        )

    try:
        convert_requirement_to_markdown(selected_source, requirement_md, overwrite=False)
    except Exception as exc:  # noqa: BLE001 - surface a clear node error.
        _set_normalization(
            state,
            performed=False,
            source_path=selected_source,
            output_path=requirement_md,
            source_type=selected_source.suffix.lstrip(".").lower(),
            skipped_reason="conversion failed",
            repo_root=repo_root,
        )
        state.errors.append(str(exc))
        return state

    _set_normalization(
        state,
        performed=True,
        source_path=selected_source,
        output_path=requirement_md,
        source_type=selected_source.suffix.lstrip(".").lower(),
        skipped_reason=None,
        repo_root=repo_root,
    )
    state.warnings.append(
        "已将 "
        f"{_relative(selected_source, repo_root)} "
        f"转换为 {_relative(requirement_md, repo_root)}"
    )
    return state
