from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from harness.domain.schemas.api_discovery import (
    ApiDiscoveryCatalog,
    DiscoveredApiCandidate,
    NetworkCall,
)

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}
SENSITIVE_KEY = re.compile(
    r"(authorization|proxy-authorization|cookie|set-cookie|token|secret|password|"
    r"api[_-]?key|session|jsessionid)",
    re.IGNORECASE,
)
PII_KEY = re.compile(
    r"(phone|mobile|id[_-]?card|identity|bank[_-]?card|card[_-]?number|real[_-]?name|"
    r"full[_-]?name|address|手机号|身份证|银行卡|姓名|地址)",
    re.IGNORECASE,
)
STATIC_RESOURCE_TYPES = {"image", "stylesheet", "font", "script", "media"}
STATIC_SUFFIXES = (
    ".js",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
)
UUID_SEGMENT = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
LONG_IDENTIFIER = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_-]{16,}$")
LONG_TOKEN = re.compile(r"^[A-Za-z0-9_-]{24,}$")


def inspect_network_capture(payload: Any, *, source: str) -> ApiDiscoveryCatalog:
    capture_format, entries, pages = _capture_entries(payload)
    calls: list[NetworkCall] = []
    candidate_observations: dict[tuple[str, str | None, str], list[dict[str, Any]]] = defaultdict(
        list
    )
    redactions: set[str] = set()

    for entry_index, raw_entry in enumerate(entries[:2000], 1):
        observation = _observation(
            raw_entry,
            entry_index=entry_index,
            pages=pages,
            redactions=redactions,
        )
        if observation is None or _is_static(observation):
            continue
        sequence = len(calls) + 1
        candidate = _is_business_candidate(observation)
        calls.append(
            NetworkCall(
                sequence=sequence,
                method=observation["method"],
                origin=observation["origin"],
                path=observation["path"],
                status=observation["status"],
                resource_type=observation["resource_type"],
                page_path=observation["page_path"],
                duration_ms=observation["duration_ms"],
                business_candidate=candidate,
            )
        )
        if candidate:
            candidate_observations[
                (observation["method"], observation["origin"], observation["path"])
            ].append(observation)
        if len(calls) >= 500:
            break

    candidates: list[DiscoveredApiCandidate] = []
    for index, ((method, origin, path), observations) in enumerate(
        sorted(
            candidate_observations.items(),
            key=lambda item: (item[0][0], item[0][1] or "", item[0][2]),
        ),
        1,
    ):
        durations = [
            item["duration_ms"] for item in observations if item["duration_ms"] is not None
        ]
        candidates.append(
            DiscoveredApiCandidate(
                candidate_id=f"DISC-{index:03d}",
                method=method,
                origin=origin,
                path=path,
                call_count=len(observations),
                status_codes=sorted(
                    {int(item["status"]) for item in observations if item["status"] is not None}
                ),
                average_duration_ms=(
                    round(sum(durations) / len(durations), 2) if durations else None
                ),
                query_parameters=sorted(
                    {name for item in observations for name in item["query_parameters"]}
                ),
                request_schema=_merge_schemas([item["request_schema"] for item in observations]),
                response_schema=_merge_schemas([item["response_schema"] for item in observations]),
                source_path=source,
                locators=[f"entry:{item['entry_index']}" for item in observations],
                pending=[
                    "该接口仅来自运行时流量观察，需与完整 OpenAPI/Swagger 契约核对。",
                    "字段必填性、枚举、错误码、权限与风控规则待契约确认。",
                ],
            )
        )

    return ApiDiscoveryCatalog(
        source_path=source,
        capture_format=capture_format,
        observed_call_count=len(calls),
        business_candidate_count=len(candidates),
        calls=calls,
        candidates=candidates,
        redactions=sorted(redactions),
        limitations=[
            "报告只描述抓包中实际观察到的流量，不代表完整 API 契约。",
            "完整响应正文不会进入发现目录，仅保留确定性结构摘要。",
            "未观察到的字段、状态码、权限、风控和业务分支仍待确认。",
        ],
    )


def _capture_entries(payload: Any) -> tuple[str, list[Any], dict[str, str]]:
    if isinstance(payload, dict) and isinstance(payload.get("log"), dict):
        log = payload["log"]
        entries = log.get("entries")
        if not isinstance(entries, list):
            raise ValueError("HAR log.entries must be an array")
        pages = {
            str(page.get("id") or ""): str(
                page.get("_url") or (page.get("pageTimings") or {}).get("_url") or ""
            )
            for page in (log.get("pages") or [])
            if isinstance(page, dict)
        }
        return "har", entries, pages
    if isinstance(payload, list):
        return "simplified_json", payload, {}
    if isinstance(payload, dict):
        for key in ("entries", "calls", "requests"):
            entries = payload.get(key)
            if isinstance(entries, list):
                return "simplified_json", entries, {}
    raise ValueError("capture must be a HAR object or simplified JSON entry array")


def _observation(
    raw_entry: Any,
    *,
    entry_index: int,
    pages: dict[str, str],
    redactions: set[str],
) -> dict[str, Any] | None:
    if not isinstance(raw_entry, dict):
        return None
    request = raw_entry.get("request")
    request = request if isinstance(request, dict) else raw_entry
    response = raw_entry.get("response")
    response = response if isinstance(response, dict) else {}
    method = str(request.get("method") or raw_entry.get("method") or "GET").upper()
    if method not in HTTP_METHODS:
        return None
    raw_url = str(request.get("url") or raw_entry.get("url") or raw_entry.get("request_url") or "")
    if not raw_url:
        return None
    parsed = urlsplit(raw_url)
    path = _normalized_path(parsed.path or "/")
    query = request.get("queryString")
    if isinstance(query, list):
        query_names = [
            str(item.get("name") or "")
            for item in query
            if isinstance(item, dict) and item.get("name")
        ]
    else:
        query_names = [name for name, _value in parse_qsl(parsed.query, keep_blank_values=True)]
    for name in query_names:
        if _is_sensitive(name):
            redactions.add(f"query:{name}")

    request_headers = _headers(request.get("headers") or raw_entry.get("request_headers"))
    response_headers = _headers(response.get("headers") or raw_entry.get("response_headers"))
    _record_header_redactions(request_headers, "request_header", redactions)
    _record_header_redactions(response_headers, "response_header", redactions)

    request_body = _request_body(request, raw_entry)
    response_body = _response_body(response, raw_entry)
    request_schema = _schema_summary(
        request_body,
        path="request",
        redactions=redactions,
    )
    response_schema = _schema_summary(
        response_body,
        path="response",
        redactions=redactions,
    )
    status = response.get("status", raw_entry.get("status"))
    try:
        normalized_status = int(status) if status is not None else None
    except (TypeError, ValueError):
        normalized_status = None
    if normalized_status is not None and not 100 <= normalized_status <= 599:
        normalized_status = None
    duration = raw_entry.get("time", raw_entry.get("duration_ms"))
    try:
        duration_ms = max(float(duration), 0) if duration is not None else None
    except (TypeError, ValueError):
        duration_ms = None
    resource_type = str(
        raw_entry.get("_resourceType")
        or raw_entry.get("resource_type")
        or raw_entry.get("resourceType")
        or ""
    ).casefold()
    content_type = (
        response_headers.get("content-type", "")
        or str((response.get("content") or {}).get("mimeType") or "")
    ).casefold()
    page_url = str(
        raw_entry.get("page_url")
        or raw_entry.get("pageUrl")
        or pages.get(str(raw_entry.get("pageref") or ""), "")
        or ""
    )
    return {
        "entry_index": entry_index,
        "method": method,
        "origin": _url_origin(parsed),
        "path": path,
        "status": normalized_status,
        "resource_type": resource_type,
        "content_type": content_type,
        "page_path": _url_path(page_url),
        "duration_ms": duration_ms,
        "query_parameters": query_names,
        "request_schema": request_schema,
        "response_schema": response_schema,
    }


def _request_body(request: dict[str, Any], raw_entry: dict[str, Any]) -> Any:
    if "request_body" in raw_entry:
        return raw_entry["request_body"]
    post_data = request.get("postData")
    if not isinstance(post_data, dict):
        return None
    if isinstance(post_data.get("params"), list):
        return {
            str(item.get("name") or ""): item.get("value")
            for item in post_data["params"]
            if isinstance(item, dict) and item.get("name")
        }
    return _json_value(post_data.get("text"))


def _response_body(response: dict[str, Any], raw_entry: dict[str, Any]) -> Any:
    if "response_body" in raw_entry:
        return raw_entry["response_body"]
    content = response.get("content")
    if not isinstance(content, dict) or content.get("encoding") == "base64":
        return None
    return _json_value(content.get("text"))


def _json_value(value: Any) -> Any:
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _headers(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key).casefold(): str(item) for key, item in value.items()}
    if isinstance(value, list):
        return {
            str(item.get("name") or "").casefold(): str(item.get("value") or "")
            for item in value
            if isinstance(item, dict) and item.get("name")
        }
    return {}


def _record_header_redactions(
    headers: dict[str, str],
    prefix: str,
    redactions: set[str],
) -> None:
    for name in headers:
        if _is_sensitive(name):
            redactions.add(f"{prefix}:{name}")


def _schema_summary(
    value: Any,
    *,
    path: str,
    redactions: set[str],
    depth: int = 0,
) -> dict[str, Any]:
    if value is None:
        return {}
    if depth >= 6:
        return {"type": _json_type(value), "truncated": True}
    if isinstance(value, dict):
        properties: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))[:100]:
            name = str(key)
            child_path = f"{path}.{name}"
            if _is_sensitive(name):
                redactions.add(child_path)
                properties[name] = {"type": _json_type(item), "redacted": True}
            else:
                properties[name] = _schema_summary(
                    item,
                    path=child_path,
                    redactions=redactions,
                    depth=depth + 1,
                )
        return {"type": "object", "properties": properties}
    if isinstance(value, list):
        variants = [
            _schema_summary(
                item,
                path=f"{path}[]",
                redactions=redactions,
                depth=depth + 1,
            )
            for item in value[:10]
        ]
        return {"type": "array", "items": _merge_schemas(variants)}
    return {"type": _json_type(value)}


def _merge_schemas(schemas: list[dict[str, Any]]) -> dict[str, Any]:
    present = [schema for schema in schemas if schema]
    if not present:
        return {}
    unique: dict[str, dict[str, Any]] = {}
    for schema in present:
        key = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        unique[key] = schema
    variants = list(unique.values())
    return variants[0] if len(variants) == 1 else {"oneOf": variants}


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "string"


def _normalized_path(path: str) -> str:
    segments = []
    for segment in unquote(path).split("/"):
        if not segment:
            continue
        if "@" in segment:
            segments.append("{redacted}")
        elif (
            segment.isdigit()
            or UUID_SEGMENT.fullmatch(segment)
            or LONG_IDENTIFIER.fullmatch(segment)
            or LONG_TOKEN.fullmatch(segment)
        ):
            segments.append("{id}")
        else:
            segments.append(segment)
    return "/" + "/".join(segments)


def _url_path(value: str) -> str | None:
    if not value:
        return None
    return _normalized_path(urlsplit(value).path or "/")


def _url_origin(parsed: Any) -> str | None:
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.casefold()
    try:
        port = parsed.port
    except ValueError:
        return None
    default_port = (parsed.scheme.casefold() == "http" and port == 80) or (
        parsed.scheme.casefold() == "https" and port == 443
    )
    authority = host if port is None or default_port else f"{host}:{port}"
    return f"{parsed.scheme.casefold()}://{authority}"


def _is_static(observation: dict[str, Any]) -> bool:
    path = observation["path"].casefold()
    return observation["resource_type"] in STATIC_RESOURCE_TYPES or path.endswith(STATIC_SUFFIXES)


def _is_business_candidate(observation: dict[str, Any]) -> bool:
    return (
        observation["resource_type"] in {"xhr", "fetch"}
        or "json" in observation["content_type"]
        or "/api/" in observation["path"].casefold()
    )


def _is_sensitive(name: str) -> bool:
    return bool(SENSITIVE_KEY.search(name) or PII_KEY.search(name))
