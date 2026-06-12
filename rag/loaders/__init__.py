"""Markdown Loader — 扫描 knowledge/ 等目录，加载 .md 文件。"""

from __future__ import annotations

from pathlib import Path

IGNORED_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime",
    ".rag_index",
    "__pycache__",
    "node_modules",
}


def find_markdown_files(directory: Path, *, recursive: bool = True) -> list[Path]:
    """在指定目录中查找所有 .md 文件。"""
    if directory.is_file():
        return [directory] if directory.suffix.lower() == ".md" else []
    if not directory.is_dir():
        return []
    if recursive:
        files: list[Path] = []
        for path in directory.rglob("*.md"):
            if any(part in IGNORED_DIR_NAMES for part in path.parts):
                continue
            files.append(path)
        return sorted(files)
    return sorted(directory.glob("*.md"))


def load_markdown_file(path: Path, *, max_chars: int | None = None) -> str:
    """读取单个 .md 文件内容。"""
    content = path.read_text(encoding="utf-8")
    if max_chars is not None and len(content) > max_chars:
        return content[:max_chars]
    return content


def load_markdown_files(
    paths: list[str | Path],
    repo_root: Path,
    *,
    max_chars_per_file: int | None = None,
) -> dict[str, str]:
    """加载多个路径下的所有 .md 文件。

    返回 {相对路径: 内容} 映射，相对路径以 '/' 为分隔。
    """
    loaded: dict[str, str] = {}
    seen: set[Path] = set()
    for base in paths:
        base_path = Path(base) if isinstance(base, str) else base
        if not base_path.is_absolute():
            base_path = repo_root / base_path
        md_files = find_markdown_files(base_path)
        for md_file in md_files:
            resolved = md_file.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                relative = md_file.relative_to(repo_root).as_posix()
                loaded[relative] = load_markdown_file(md_file, max_chars=max_chars_per_file)
            except ValueError:
                # 不在 repo_root 下，用完整路径作为 key
                loaded[str(md_file)] = load_markdown_file(md_file, max_chars=max_chars_per_file)
    return loaded
