"""CLI: PRD 工作区导入 / 创建工具。"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from runtime.workspace import (
    PRDWorkspace,
    default_metadata,
    read_yaml_mapping,
    write_yaml_mapping,
)


def _workspace_name(path: Path) -> str:
    """从文件路径生成工作区名字。"""
    stem = path.stem
    for prefix in ("需求", "requirement", "prd_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
            break
    stem = "".join(c for c in stem if c.isalnum() or c in "-_")
    return stem or "default"


def _safe_workspace_name(value: str) -> str:
    stem = "".join(c for c in value.strip() if c.isalnum() or c in "-_")
    return stem[:80] or f"requirement-{datetime.now().strftime('%Y%m%d%H%M%S')}"


def _init_workspace_metadata(workspace_dir: Path, name: str) -> None:
    """创建初始 metadata.yml。"""
    metadata = default_metadata(name, name, "agentic-qa")
    metadata_path = PRDWorkspace(workspace_dir).metadata_path
    if not metadata_path.is_file():
        write_yaml_mapping(metadata_path, metadata)


def _ensure_prd_workspace(
    repo_root: Path,
    prd_path_str: str,
) -> str:
    """确保 PRD 工作区存在，返回相对路径字符串。"""
    candidate = Path(prd_path_str)

    # 情况 1: 已经是 prd/<name> 相对路径
    if not candidate.is_absolute():
        if not prd_path_str.startswith("prd/"):
            prd_path_str = f"prd/{prd_path_str}"
        full = repo_root / prd_path_str
        if full.is_dir():
            return prd_path_str
        full.mkdir(parents=True, exist_ok=True)
        _init_workspace_metadata(full, candidate.name)
        return prd_path_str

    # 情况 2: 绝对路径，已经是目录
    if candidate.is_dir():
        try:
            rel = candidate.relative_to(repo_root)
            return rel.as_posix()
        except ValueError:
            return _import_external_directory(repo_root, candidate)

    # 情况 3: 绝对路径，是一个源文件
    if candidate.is_file():
        return _import_source_file(repo_root, candidate)

    raise FileNotFoundError(f"文件或目录不存在: {prd_path_str}")


def _import_source_file(repo_root: Path, source_file: Path) -> str:
    """从单个源文件创建 PRD 工作区。"""
    name = _workspace_name(source_file)
    prd_rel = f"prd/{name}"
    workspace_dir = repo_root / prd_rel
    workspace_dir.mkdir(parents=True, exist_ok=True)
    input_dir = workspace_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    dest = input_dir / f"requirement{source_file.suffix}"
    if not dest.is_file():
        shutil.copy2(source_file, dest)
    _init_workspace_metadata(workspace_dir, name)
    print(f"📁 创建 PRD 工作区: {prd_rel} （来源: {source_file}）")
    return prd_rel


def _import_external_directory(repo_root: Path, external_dir: Path) -> str:
    """从外部目录导入为 PRD 工作区。"""
    name = _workspace_name(external_dir)
    prd_rel = f"prd/{name}"
    workspace_dir = repo_root / prd_rel
    workspace_dir.mkdir(parents=True, exist_ok=True)
    input_dir = workspace_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("*.md", "*.pdf", "*.docx", "*.txt", "*.html"):
        for f in external_dir.glob(ext):
            dest = input_dir / f.name
            if not dest.is_file():
                shutil.copy2(f, dest)
    _init_workspace_metadata(workspace_dir, name)
    print(f"📁 导入外部工作区: {prd_rel} （来源: {external_dir}）")
    return prd_rel


def _import_markdown_requirement(
    repo_root: Path,
    markdown: str,
    *,
    title: str = "manual-markdown-requirement",
    source_url: str | None = None,
    source_type: str = "manual_markdown",
) -> str:
    """Create a PRD workspace from already-normalized Markdown text."""
    name = _safe_workspace_name(title)
    prd_rel = f"prd/{name}"
    workspace_dir = repo_root / prd_rel
    workspace_dir.mkdir(parents=True, exist_ok=True)
    input_dir = workspace_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    requirement_md = input_dir / "requirement.md"
    requirement_md.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    _init_workspace_metadata(workspace_dir, name)
    metadata_path = PRDWorkspace(workspace_dir).metadata_path
    metadata = read_yaml_mapping(metadata_path)
    metadata["source_type"] = source_type
    if source_url:
        metadata["source_url"] = source_url
    write_yaml_mapping(metadata_path, metadata)
    print(f"📁 创建 PRD 工作区: {prd_rel} （来源: inline markdown）")
    return prd_rel


def _import_feishu_url(repo_root: Path, url: str) -> str:
    """从飞书链接导入 PRD 工作区。"""
    from runtime.tools.feishu_fetcher import fetch_feishu_doc as _fetch_feishu_doc
    from runtime.tools.feishu_fetcher import is_feishu_url as _is_feishu_url

    if not _is_feishu_url(url):
        raise ValueError(f"不是飞书链接: {url}")
    document = _fetch_feishu_doc(url)
    if isinstance(document, tuple):
        title, content = document
    else:
        title = document.title
        content = document.content
    return _import_markdown_requirement(
        repo_root,
        content,
        title=title,
        source_url=url,
        source_type="feishu",
    )


def _import_network_capture_to_workspace(
    repo_root: Path,
    prd_path: str,
    capture_path: str,
) -> Path:
    """Copy a HAR/JSON network capture into the PRD input standard location."""
    source = Path(capture_path)
    if not source.is_absolute():
        source = repo_root / source
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"抓包文件不存在: {capture_path}")

    suffix = source.suffix.lower()
    if suffix not in {".har", ".json"}:
        raise ValueError(f"抓包文件仅支持 .har/.json: {capture_path}")

    workspace = PRDWorkspace(repo_root / prd_path)
    target_name = "network-capture.har" if suffix == ".har" else "network-capture.json"
    target = workspace.root / "input" / target_name
    target.parent.mkdir(parents=True, exist_ok=True)
    if source != target.resolve():
        shutil.copy2(source, target)
    return target
