from __future__ import annotations

from pathlib import Path
from typing import Any

MarkItDown: Any = None


def _load_markitdown() -> Any:
    global MarkItDown  # noqa: PLW0603 - cache optional dependency after first conversion.
    if MarkItDown is None:
        try:
            from markitdown import MarkItDown as LoadedMarkItDown
        except ImportError as exc:  # pragma: no cover - only used when dependency is missing.
            raise RuntimeError("MarkItDown 未安装，无法转换需求文档。") from exc
        MarkItDown = LoadedMarkItDown
    return MarkItDown


def convert_requirement_to_markdown(
    source_path: Path,
    output_path: Path,
    *,
    overwrite: bool = False,
) -> str:
    source_path = source_path.resolve()
    output_path = output_path.resolve()

    if not source_path.is_file():
        raise FileNotFoundError(f"需求源文件不存在: {source_path}")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"目标 requirement.md 已存在，默认不覆盖: {output_path}")

    try:
        result = _load_markitdown()().convert(source_path)
        markdown = (getattr(result, "markdown", None) or result.text_content or "").strip()
    except Exception as exc:  # noqa: BLE001 - conversion libraries raise varied errors.
        raise RuntimeError(f"MarkItDown 转换失败: {source_path.name}: {exc}") from exc

    if not markdown:
        raise RuntimeError(f"MarkItDown 转换结果为空: {source_path.name}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown + "\n", encoding="utf-8")
    return markdown
