from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from runtime.tools.openapi_normalizer import (
    NormalizedApiDocument,
    normalize_openapi_document,
    render_openapi_markdown,
)
from runtime.workspace import PRDWorkspace, resolve_prd_path

API_DOC_FILENAMES = (
    "api.openapi.json",
    "api.swagger.json",
    "api.apifox.json",
    "api.openapi.yaml",
    "api.openapi.yml",
    "api.swagger.yaml",
    "api.swagger.yml",
    "api.apifox.yaml",
    "api.apifox.yml",
)
API_DOC_EXTENSIONS = {".json", ".yaml", ".yml"}


@dataclass(frozen=True)
class ApiDocLoadResult:
    source_path: Path
    raw_payload: dict[str, Any]
    document: NormalizedApiDocument
    markdown: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ApiDocImportResult:
    copied_path: Path
    markdown_path: Path
    document: NormalizedApiDocument
    warnings: list[str] = field(default_factory=list)


def is_supported_api_doc_path(path: Path) -> bool:
    return path.suffix.lower() in API_DOC_EXTENSIONS


def load_api_document(path: Path) -> ApiDocLoadResult:
    payload = _read_api_payload(path)
    document = normalize_openapi_document(payload, source_path=path.as_posix())
    markdown = render_openapi_markdown(document)
    return ApiDocLoadResult(
        source_path=path,
        raw_payload=payload,
        document=document,
        markdown=markdown,
        warnings=list(document.warnings),
    )


def normalize_workspace_api_docs(
    repo_root: Path, prd_path: str | Path
) -> ApiDocImportResult | None:
    workspace = PRDWorkspace(resolve_prd_path(repo_root, str(prd_path)))
    api_md = workspace.api_path
    source = _first_workspace_api_doc(workspace)
    if source is None:
        return None
    result = load_api_document(source)
    api_md.parent.mkdir(parents=True, exist_ok=True)
    api_md.write_text(result.markdown, encoding="utf-8")
    return ApiDocImportResult(
        copied_path=source,
        markdown_path=api_md,
        document=result.document,
        warnings=result.warnings,
    )


def import_api_document_to_workspace(
    repo_root: Path,
    prd_path: str | Path,
    api_doc_path: str | Path,
) -> ApiDocImportResult:
    source = Path(api_doc_path)
    if not source.is_absolute():
        source = repo_root / source
    if not source.is_file():
        raise FileNotFoundError(f"API 文档不存在: {api_doc_path}")
    if not is_supported_api_doc_path(source):
        raise ValueError(f"不支持的 API 文档格式: {source.suffix}")

    workspace = PRDWorkspace(resolve_prd_path(repo_root, str(prd_path)))
    input_dir = workspace.root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    target = input_dir / _target_api_doc_name(source)
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    result = load_api_document(target)
    workspace.api_path.write_text(result.markdown, encoding="utf-8")
    return ApiDocImportResult(
        copied_path=target,
        markdown_path=workspace.api_path,
        document=result.document,
        warnings=result.warnings,
    )


def _read_api_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(text)
        else:
            payload = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"OpenAPI JSON/YAML 无法解析: {path.as_posix()}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"OpenAPI JSON/YAML 顶层必须是对象: {path.as_posix()}")
    return payload


def _target_api_doc_name(source: Path) -> str:
    suffix = source.suffix.lower()
    return "api.openapi.json" if suffix == ".json" else f"api.openapi{suffix}"


def _first_workspace_api_doc(workspace: PRDWorkspace) -> Path | None:
    for filename in API_DOC_FILENAMES:
        path = workspace.root / "input" / filename
        if path.is_file():
            return path
    return None
