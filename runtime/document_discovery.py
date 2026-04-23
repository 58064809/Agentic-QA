from __future__ import annotations

import re
from pathlib import Path
from typing import Any

TEXT_DOC_SUFFIXES = {".md", ".txt", ".rst"}
BINARY_DOC_SUFFIXES = {".pdf", ".docx"}
PROTOTYPE_SUFFIXES = {
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".svg",
    ".fig",
    ".drawio",
}
IGNORED_PARTS = {
    ".git",
    ".idea",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "outputs",
}
REQUIREMENT_HINTS = ("prd", "requirement", "spec", "需求", "产品", "story")
PROTOTYPE_HINTS = ("prototype", "design", "原型", "设计", "html")
SEARCH_DIR_HINTS = (
    "docs",
    "doc",
    "prd",
    "requirements",
    "spec",
    "specs",
    "design",
    "prototype",
    "需求",
    "原型",
)
QUERY_STOPWORDS = {
    "帮我",
    "请",
    "分析",
    "需求",
    "生成",
    "测试",
    "用例",
    "脚本",
    "执行",
    "日志",
    "结果",
    "看看",
    "原型图",
    "prd",
    "pytest",
}


def _should_skip(path: Path) -> bool:
    if any(part in IGNORED_PARTS for part in path.parts):
        return True
    return path.name.lower() == "readme.md"


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _extract_query_tokens(user_text: str) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_./\\-]{3,}", user_text)
    result: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in QUERY_STOPWORDS:
            continue
        result.append(lowered)
    return result


def _extract_explicit_paths(user_text: str, workspace_root: Path) -> list[Path]:
    suffixes = "md|txt|rst|pdf|docx|html|htm|png|jpg|jpeg|webp|gif|svg|fig|drawio"
    patterns = re.findall(
        rf"[A-Za-z]:\\[^\s\"']+|(?:\.{{0,2}}[\\/])?[A-Za-z0-9_\-/\\.]+\.(?:{suffixes})",
        user_text,
    )
    result: list[Path] = []
    for raw_path in patterns:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
        result.append(candidate)
    return result


def _discover_requirement_packages(workspace_root: Path) -> list[Path]:
    package_root = workspace_root / "requirements"
    if not package_root.is_dir():
        return []
    return sorted(path for path in package_root.iterdir() if path.is_dir() and not _should_skip(path))


def _score_package(package_root: Path, tokens: list[str], explicit_paths: set[Path]) -> int:
    lowered_path = str(package_root).lower()
    score = 0

    if any(_is_relative_to(path, package_root) for path in explicit_paths):
        score += 80
    for token in tokens:
        if token in lowered_path:
            score += 16

    for path in package_root.rglob("*"):
        if not path.is_file() or _should_skip(path):
            continue
        lowered_file = str(path).lower()
        if any(token in lowered_file for token in tokens):
            score += 3

    return score


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _select_requirement_package(
    workspace_root: Path,
    tokens: list[str],
    explicit_paths: set[Path],
) -> dict[str, Any] | None:
    packages = _discover_requirement_packages(workspace_root)
    if not packages:
        return None

    scored = [(package, _score_package(package, tokens, explicit_paths)) for package in packages]
    scored.sort(key=lambda item: (-item[1], item[0].name))

    if scored[0][1] > 0:
        matched_by = "query_or_path"
        selected = scored[0][0]
    elif len(scored) == 1:
        matched_by = "single_package_default"
        selected = scored[0][0]
    else:
        return None

    return {
        "name": selected.name,
        "root": str(selected),
        "relative_root": _safe_relative(selected, workspace_root),
        "matched_by": matched_by,
        "available_packages": [package.name for package in packages],
    }


def _score_document(path: Path, tokens: list[str], explicit_paths: set[Path]) -> int:
    lowered_path = str(path).lower()
    lowered_parent = str(path.parent).lower()
    score = 0

    if path.resolve() in explicit_paths:
        score += 40
    if any(hint in path.stem.lower() for hint in REQUIREMENT_HINTS):
        score += 12
    if any(hint in lowered_parent for hint in SEARCH_DIR_HINTS):
        score += 5
    if path.suffix.lower() in TEXT_DOC_SUFFIXES:
        score += 3

    for token in tokens:
        if token in lowered_path:
            score += 4

    return score


def _score_prototype(path: Path, tokens: list[str], explicit_paths: set[Path]) -> int:
    lowered_path = str(path).lower()
    lowered_parent = str(path.parent).lower()
    score = 0

    if path.resolve() in explicit_paths:
        score += 40
    if any(hint in lowered_path for hint in PROTOTYPE_HINTS):
        score += 10
    if any(hint in lowered_parent for hint in SEARCH_DIR_HINTS):
        score += 6

    for token in tokens:
        if token in lowered_path:
            score += 3

    return score


def _read_excerpt(path: Path, limit: int = 50000) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")[:limit]


def _build_asset(path: Path, workspace_root: Path, score: int, include_content: bool) -> dict[str, Any]:
    suffix = path.suffix.lower()
    asset = {
        "path": _safe_relative(path, workspace_root),
        "score": score,
        "suffix": suffix,
        "size_bytes": path.stat().st_size,
    }
    if include_content:
        asset["content"] = _read_excerpt(path)
    return asset


def discover_requirement_context(
    workspace_root: Path,
    user_text: str,
    max_docs: int = 2,
    max_prototypes: int = 12,
) -> dict[str, Any]:
    workspace_root = Path(workspace_root)
    tokens = _extract_query_tokens(user_text)
    explicit_paths = {path.resolve() for path in _extract_explicit_paths(user_text, workspace_root)}
    package = _select_requirement_package(workspace_root, tokens, explicit_paths)
    scan_root = Path(package["root"]) if package else workspace_root
    docs: list[dict[str, Any]] = []
    prototypes: list[dict[str, Any]] = []

    for path in scan_root.rglob("*"):
        if not path.is_file() or _should_skip(path):
            continue

        suffix = path.suffix.lower()
        if suffix in TEXT_DOC_SUFFIXES | BINARY_DOC_SUFFIXES:
            score = _score_document(path, tokens, explicit_paths)
            if score > 0:
                docs.append(_build_asset(path, workspace_root, score, include_content=suffix in TEXT_DOC_SUFFIXES))
            continue

        if suffix in PROTOTYPE_SUFFIXES:
            score = _score_prototype(path, tokens, explicit_paths)
            if score > 0:
                prototypes.append(_build_asset(path, workspace_root, score, include_content=False))

    docs.sort(key=lambda item: (-item["score"], item["path"]))
    prototypes.sort(key=lambda item: (-item["score"], item["path"]))

    selected_docs = docs[:max_docs]
    selected_prototypes = prototypes[:max_prototypes]
    missing: list[str] = []

    if not selected_docs:
        missing.append("未发现可读取的 PRD/需求文档")
    if not selected_prototypes:
        missing.append("未发现原型图或设计稿文件")

    return {
        "workspace_root": str(workspace_root),
        "output_root": str(scan_root),
        "query_tokens": tokens,
        "requirement_package": package,
        "selected_requirement_docs": selected_docs,
        "selected_prototypes": selected_prototypes,
        "missing_context": missing,
    }
