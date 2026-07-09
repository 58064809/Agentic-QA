from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runtime.tools.openapi_normalizer import HTTP_METHODS
from runtime.workspace import resolve_prd_path


@dataclass(frozen=True)
class OpenApiOperationChunk:
    chunk_id: str
    service: str
    method: str
    path: str
    summary: str
    tags: list[str]
    parameters: list[dict[str, Any]]
    request_schema: dict[str, Any]
    response_schema: dict[str, Any]
    response_status_codes: list[str]
    security: list[Any]
    source_path: str
    confidence: str = "high"
    matched_by: str = "api_scope"

    def as_context(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "service": self.service,
            "method": self.method,
            "path": self.path,
            "summary": self.summary,
            "tags": self.tags,
            "parameters": self.parameters,
            "request_schema": self.request_schema,
            "response_schema": self.response_schema,
            "response_status_codes": self.response_status_codes,
            "security": self.security,
            "source_path": self.source_path,
            "confidence": self.confidence,
            "matched_by": self.matched_by,
        }


@dataclass(frozen=True)
class ApiScope:
    service: str = ""
    operations: list[tuple[str | None, str]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


def load_service_openapi_chunks(repo_root: Path, service: str) -> list[OpenApiOperationChunk]:
    source = repo_root / "knowledge" / "api" / service / "openapi.json"
    if not source.is_file():
        return []
    payload = json.loads(source.read_text(encoding="utf-8"))
    return build_openapi_operation_chunks(
        payload,
        service=service,
        source_path=source.relative_to(repo_root).as_posix(),
    )


def build_openapi_operation_chunks(
    payload: dict[str, Any], *, service: str, source_path: str
) -> list[OpenApiOperationChunk]:
    paths = payload.get("paths")
    if not isinstance(paths, dict):
        return []
    global_security = payload.get("security") if isinstance(payload.get("security"), list) else []
    chunks: list[OpenApiOperationChunk] = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        common_parameters = _parameters(path_item.get("parameters"), payload)
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            method_upper = method.upper()
            tags = [str(tag) for tag in operation.get("tags", []) if tag]
            if not tags:
                tags = [_domain_from_path(str(path))]
            security = operation.get("security")
            if not isinstance(security, list):
                security = global_security
            chunks.append(
                OpenApiOperationChunk(
                    chunk_id=_chunk_id(service, method_upper, str(path)),
                    service=service,
                    method=method_upper,
                    path=str(path),
                    summary=str(operation.get("summary") or operation.get("description") or ""),
                    tags=tags,
                    parameters=[
                        *common_parameters,
                        *_parameters(operation.get("parameters"), payload),
                    ],
                    request_schema=_request_body_schema(operation, payload),
                    response_schema=_response_schema(operation, payload),
                    response_status_codes=_response_status_codes(operation),
                    security=security,
                    source_path=source_path,
                )
            )
    return chunks


def retrieve_openapi_chunks_for_prd(
    repo_root: Path,
    prd_path: str,
    *,
    requirement_text: str = "",
    max_chunks: int = 8,
) -> tuple[list[OpenApiOperationChunk], list[str]]:
    scope = load_api_scope(repo_root, prd_path)
    if not scope.service:
        return [], []
    chunks = load_service_openapi_chunks(repo_root, scope.service)
    if not chunks:
        return [], [f"未找到服务级 OpenAPI: knowledge/api/{scope.service}/openapi.json"]
    if scope.operations:
        selected: list[OpenApiOperationChunk] = []
        warnings: list[str] = []
        by_path_method = {(chunk.path, chunk.method): chunk for chunk in chunks}
        by_path = {}
        for chunk in chunks:
            by_path.setdefault(chunk.path, []).append(chunk)
        for method, path in scope.operations:
            if method:
                chunk = by_path_method.get((path, method.upper()))
                if chunk:
                    selected.append(chunk)
                else:
                    warnings.append(
                        "api-scope.md 指定的接口未命中 OpenAPI: " f"{method.upper()} {path}"
                    )
            else:
                matches = by_path.get(path, [])
                if matches:
                    selected.extend(matches)
                else:
                    warnings.append(f"api-scope.md 指定的接口未命中 OpenAPI: {path}")
        return _unique_chunks(selected)[:max_chunks], warnings

    query_terms = [*scope.keywords, *_keywords(requirement_text)]
    if not query_terms:
        return [], ["api-scope.md 声明了 service 但未列出 path/method，且 PRD 关键词不足。"]
    scored = [(score_openapi_chunk(chunk, query_terms), chunk) for chunk in chunks]
    selected = [
        _with_confidence(chunk, confidence="medium", matched_by="keyword")
        for score, chunk in sorted(scored, key=lambda item: item[0], reverse=True)
        if score > 0
    ][:max_chunks]
    return selected, [] if selected else ["未根据 PRD 关键词命中服务级 OpenAPI 接口。"]


def load_api_scope(repo_root: Path, prd_path: str) -> ApiScope:
    if not prd_path:
        return ApiScope()
    scope_path = resolve_prd_path(repo_root, prd_path) / "input" / "api-scope.md"
    if not scope_path.is_file():
        return ApiScope()
    return parse_api_scope(scope_path.read_text(encoding="utf-8"))


def parse_api_scope(content: str) -> ApiScope:
    service = ""
    operations: list[tuple[str | None, str]] = []
    keywords: list[str] = []
    in_paths = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if re.match(r"(?i)^paths\s*:", line):
            in_paths = True
            inline = line.split(":", 1)[1].strip()
            if inline:
                operations.extend(_parse_scope_operation(inline))
            continue
        if re.match(r"(?i)^service\s*:", line):
            service = line.split(":", 1)[1].strip().strip("`'\"")
            in_paths = False
            continue
        if re.match(r"(?i)^keywords\s*:", line):
            values = line.split(":", 1)[1]
            keywords.extend(_split_keywords(values))
            in_paths = False
            continue
        if line.startswith("-"):
            value = line[1:].strip()
            parsed = _parse_scope_operation(value)
            if in_paths or parsed:
                operations.extend(parsed)
            else:
                keywords.extend(_split_keywords(value))
    return ApiScope(service=service, operations=operations, keywords=keywords)


def score_openapi_chunk(chunk: OpenApiOperationChunk, query_terms: list[str]) -> int:
    haystack = " ".join([chunk.path, chunk.summary, " ".join(chunk.tags)]).lower()
    return sum(1 for term in query_terms if term and term.lower() in haystack)


def _parse_scope_operation(value: str) -> list[tuple[str | None, str]]:
    value = value.strip().strip("`")
    if not value:
        return []
    match = re.match(r"(?i)^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)\s+(.+)$", value)
    if match:
        return [(match.group(1).upper(), match.group(2).strip())]
    if value.startswith("/"):
        return [(None, value)]
    return []


def _split_keywords(value: str) -> list[str]:
    return [item.strip(" `，,") for item in re.split(r"[,，\s]+", value) if item.strip(" `，,")]


def _keywords(text: str) -> list[str]:
    return [item for item in _split_keywords(text) if len(item) >= 2][:20]


def _parameters(value: Any, root: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    parameters: list[dict[str, Any]] = []
    for item in value:
        parameter = resolve_schema_refs(item, root)
        if not isinstance(parameter, dict):
            continue
        schema = resolve_schema_refs(parameter.get("schema"), root)
        parameters.append(
            {
                "name": str(parameter.get("name") or ""),
                "in": str(parameter.get("in") or ""),
                "required": bool(parameter.get("required")),
                "description": str(parameter.get("description") or ""),
                "schema": schema if isinstance(schema, dict) else {},
            }
        )
    return parameters


def _request_body_schema(operation: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    request_body = resolve_schema_refs(operation.get("requestBody"), root)
    if not isinstance(request_body, dict):
        return {}
    content = request_body.get("content")
    if not isinstance(content, dict):
        return {}
    media = content.get("application/json") or next(iter(content.values()), {})
    if not isinstance(media, dict):
        return {}
    schema = resolve_schema_refs(media.get("schema"), root)
    return schema if isinstance(schema, dict) else {}


def _response_schema(operation: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return {}
    success_codes = [str(code) for code in responses if str(code).startswith(("2", "3"))]
    selected_code = success_codes[0] if success_codes else next(iter(responses), "")
    response = resolve_schema_refs(responses.get(selected_code), root)
    if not isinstance(response, dict):
        return {}
    content = response.get("content")
    if isinstance(content, dict):
        media = content.get("application/json") or next(iter(content.values()), {})
        if isinstance(media, dict):
            schema = resolve_schema_refs(media.get("schema"), root)
            return schema if isinstance(schema, dict) else {}
    schema = resolve_schema_refs(response.get("schema"), root)
    return schema if isinstance(schema, dict) else {}


def _response_status_codes(operation: dict[str, Any]) -> list[str]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return []
    return [str(code) for code in responses if str(code).startswith(("2", "3"))]


def resolve_schema_refs(value: Any, root: dict[str, Any], seen: set[str] | None = None) -> Any:
    if seen is None:
        seen = set()
    if isinstance(value, list):
        return [resolve_schema_refs(item, root, seen) for item in value]
    if not isinstance(value, dict):
        return value
    ref = value.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        if ref in seen:
            return {"$ref": ref}
        target = _resolve_pointer(root, ref)
        if target is None:
            return value
        merged = {key: item for key, item in value.items() if key != "$ref"}
        if isinstance(target, dict):
            return resolve_schema_refs({**target, **merged}, root, {*seen, ref})
        return target
    return {key: resolve_schema_refs(item, root, seen) for key, item in value.items()}


def _resolve_pointer(root: dict[str, Any], ref: str) -> Any:
    current: Any = root
    for raw_part in ref.removeprefix("#/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _domain_from_path(path: str) -> str:
    segments = [segment for segment in path.strip("/").split("/") if segment]
    ignored = {"api", "mobile", "app", "product", "common"}
    for segment in segments:
        normalized = re.sub(r"[^A-Za-z0-9_-]", "", segment)
        if normalized and normalized not in ignored:
            return normalized
    return segments[0] if segments else "general"


def _chunk_id(service: str, method: str, path: str) -> str:
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]
    return f"openapi.{service}.{method}.{digest}"


def _with_confidence(
    chunk: OpenApiOperationChunk, *, confidence: str, matched_by: str
) -> OpenApiOperationChunk:
    return OpenApiOperationChunk(
        chunk_id=chunk.chunk_id,
        service=chunk.service,
        method=chunk.method,
        path=chunk.path,
        summary=chunk.summary,
        tags=chunk.tags,
        parameters=chunk.parameters,
        request_schema=chunk.request_schema,
        response_schema=chunk.response_schema,
        response_status_codes=chunk.response_status_codes,
        security=chunk.security,
        source_path=chunk.source_path,
        confidence=confidence,
        matched_by=matched_by,
    )


def _unique_chunks(chunks: list[OpenApiOperationChunk]) -> list[OpenApiOperationChunk]:
    seen: set[str] = set()
    selected: list[OpenApiOperationChunk] = []
    for chunk in chunks:
        key = f"{chunk.method} {chunk.path}"
        if key in seen:
            continue
        seen.add(key)
        selected.append(chunk)
    return selected
