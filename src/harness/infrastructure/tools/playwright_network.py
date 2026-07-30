from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl

from harness.domain.schemas.api_discovery import ApiDiscoveryCatalog
from harness.infrastructure.tools.network_capture import inspect_network_capture

NETWORK_LINE = re.compile(
    r"^\s*(?P<index>\d+)\.\s+\[(?P<method>[A-Z]+)]\s+"
    r"(?P<url>\S+?)(?:\s+=>\s+\[(?P<status>\d{3})](?:[ \t]+[^\r\n]+)?)?[ \t]*$",
    re.MULTILINE,
)
DETAIL_LINE = re.compile(
    r"^\s*#(?P<index>\d+)\s+\[(?P<method>[A-Z]+)]\s+(?P<url>\S+)\s*$",
    re.MULTILINE,
)
EMPTY_BODY = re.compile(
    r"\b(no|without|empty|unavailable|not available)\b.{0,40}\b(body|content)\b",
    re.IGNORECASE | re.DOTALL,
)


def inspect_playwright_network(
    call_mcp: Callable[[dict[str, Any]], Any],
    *,
    max_requests: int,
    source: str,
) -> ApiDiscoveryCatalog:
    bounded_max = min(max(max_requests, 1), 25)
    listed = call_mcp(
        {
            "tool": "browser_network_requests",
            "arguments": {"static": False},
        }
    )
    summaries = _network_summaries(_mcp_text(listed))
    entries: list[dict[str, Any]] = []
    detail_failures = 0
    for summary in summaries[:bounded_max]:
        try:
            details = _mcp_text(
                call_mcp(
                    {
                        "tool": "browser_network_request",
                        "arguments": {"index": summary["index"]},
                    }
                )
            )
            entry = _detail_entry(details, fallback=summary)
            if _looks_like_business_request(entry):
                request_content_type = str(entry["request_headers"].get("content-type") or "")
                entry["request_body"] = _body_value(
                    _network_body(call_mcp, summary["index"], "request-body"),
                    content_type=request_content_type,
                )
                entry["response_body"] = _body_value(
                    _network_body(call_mcp, summary["index"], "response-body"),
                    content_type=str(entry["response_headers"].get("content-type") or ""),
                )
            entries.append(entry)
        except (RuntimeError, ValueError):
            detail_failures += 1
            entries.append(
                {
                    "method": summary["method"],
                    "url": summary["url"],
                    "status": summary["status"],
                }
            )

    catalog = inspect_network_capture({"entries": entries}, source=source).model_copy(
        update={"capture_format": "playwright_mcp"}
    )
    limitations = list(catalog.limitations)
    if len(summaries) > bounded_max:
        limitations.append(
            f"本次仅检查前 {bounded_max} 条非静态网络请求，共观察到 {len(summaries)} 条。"
        )
    if detail_failures:
        limitations.append(f"{detail_failures} 条请求详情不可用，仅保留 method、URL 和状态码摘要。")
    return catalog.model_copy(update={"limitations": list(dict.fromkeys(limitations))})


def _mcp_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ValueError("Playwright MCP result must be an object")
    if payload.get("isError") is True or payload.get("is_error") is True:
        raise RuntimeError("Playwright MCP returned an error")
    content = payload.get("content")
    if not isinstance(content, list):
        raise ValueError("Playwright MCP result is missing content")
    texts = [
        str(item.get("text") or "")
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    if not texts:
        raise ValueError("Playwright MCP result has no text content")
    text = "\n".join(texts)
    if text.lstrip().startswith("### Error"):
        raise RuntimeError("Playwright MCP returned an error")
    return text


def _network_summaries(text: str) -> list[dict[str, Any]]:
    summaries = []
    for match in NETWORK_LINE.finditer(text):
        status = match.group("status")
        summaries.append(
            {
                "index": int(match.group("index")),
                "method": match.group("method"),
                "url": match.group("url"),
                "status": int(status) if status else None,
            }
        )
    return summaries


def _detail_entry(text: str, *, fallback: dict[str, Any]) -> dict[str, Any]:
    headline = DETAIL_LINE.search(text)
    method = headline.group("method") if headline else fallback["method"]
    url = headline.group("url") if headline else fallback["url"]
    status = fallback["status"]
    duration_ms: float | None = None
    resource_type = ""
    request_headers: dict[str, str] = {}
    response_headers: dict[str, str] = {}
    section = ""
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped in {"General", "Request headers", "Response headers"}:
            section = stripped
            continue
        if ":" not in stripped:
            continue
        name, value = (part.strip() for part in stripped.split(":", 1))
        key = name.casefold()
        if section == "General":
            if key == "status":
                matched = re.search(r"\b([1-5]\d{2})\b", value)
                status = int(matched.group(1)) if matched else status
            elif key == "duration":
                matched = re.search(r"(\d+(?:\.\d+)?)\s*ms", value, re.IGNORECASE)
                duration_ms = float(matched.group(1)) if matched else None
            elif key == "type":
                resource_type = value.casefold()
        elif section == "Request headers":
            request_headers[key] = value if key == "content-type" else ""
        elif section == "Response headers":
            response_headers[key] = value if key == "content-type" else ""
    return {
        "method": method,
        "url": url,
        "status": status,
        "resource_type": resource_type,
        "duration_ms": duration_ms,
        "request_headers": request_headers,
        "response_headers": response_headers,
    }


def _network_body(
    call_mcp: Callable[[dict[str, Any]], Any],
    index: int,
    part: str,
) -> str | None:
    try:
        text = _mcp_text(
            call_mcp(
                {
                    "tool": "browser_network_request",
                    "arguments": {"index": index, "part": part},
                }
            )
        )
    except (RuntimeError, ValueError):
        return None
    body = text.split("### Result", 1)[-1].strip()
    if not body or EMPTY_BODY.search(body):
        return None
    if body.startswith("```") and body.endswith("```"):
        lines = body.splitlines()
        body = "\n".join(lines[1:-1]).strip()
    return body[:50_000] or None


def _body_value(value: str | None, *, content_type: str) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        pass
    if "application/x-www-form-urlencoded" in content_type.casefold():
        return {name: item for name, item in parse_qsl(value, keep_blank_values=True)}
    return value


def _looks_like_business_request(entry: dict[str, Any]) -> bool:
    return (
        str(entry.get("resource_type") or "").casefold() in {"xhr", "fetch"}
        or "json" in str((entry.get("response_headers") or {}).get("content-type") or "").casefold()
        or "/api/" in str(entry.get("url") or "").casefold()
    )
