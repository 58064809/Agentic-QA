"""Playwright network capture utility — auto-generates HAR from page responses.

Usage during UI test execution::

    from runtime.tools.network_capture import NetworkCapture

    capture = NetworkCapture()
    page.on("response", capture.on_response)
    # ... run your page interactions ...
    capture.save("prd/my-requirement/input/network-capture.json")
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from runtime.tools.network_sanitizer import sanitize_headers, sanitize_json, schema_summary


class NetworkCapture:
    """Listen to Playwright ``page.on("response")`` and build a HAR-like snapshot.

    Call ``on_response(response)`` for every intercepted response, then
    ``save(output_path)`` to persist the snapshot for ``api_discovery``.
    """

    def __init__(self, *, save_body: bool = False, max_body_chars: int = 50_000) -> None:
        """Create a capture collector.

        ``save_body`` is intentionally off by default. Runtime consumers only
        need schema summaries for API discovery, while full bodies frequently
        contain tokens or personal data.
        """
        self.save_body = save_body
        self.max_body_chars = max_body_chars
        self._calls: list[dict[str, Any]] = []

    def on_response(self, response: Any) -> None:
        """Playwright ``page.on("response")`` handler.

        Accepts a Playwright ``Response`` object (or any duck-typed object
        with ``url``, ``status``, ``request``, ``headers``, ``body``).
        """
        try:
            url = str(response.url)
            status = response.status
            req = response.request
            method = str(req.method).upper() if req else "GET"
            req_headers = dict(req.headers) if req else {}
            resp_headers = dict(response.headers)

            request_body = _json_like(_request_body(req))
            response_body = _json_like(_response_body(response))
            sanitized_request_body = (
                sanitize_json(request_body) if request_body is not None else None
            )
            sanitized_response_body = (
                sanitize_json(response_body) if response_body is not None else None
            )

            entry: dict[str, Any] = {
                "url": url,
                "method": method,
                "status": status,
                "request_headers": sanitize_headers(req_headers),
                "response_headers": sanitize_headers(resp_headers),
                "request_body_schema": (
                    schema_summary(sanitized_request_body)
                    if sanitized_request_body is not None
                    else {}
                ),
                "response_body_schema": (
                    schema_summary(sanitized_response_body)
                    if sanitized_response_body is not None
                    else {}
                ),
                "timestamp": time.time(),
                "resource_type": _detect_resource_type(url, resp_headers),
            }
            if self.save_body:
                if sanitized_request_body is not None:
                    entry["request_body"] = _bounded_body(
                        sanitized_request_body,
                        max_chars=self.max_body_chars,
                    )
                if sanitized_response_body is not None:
                    entry["response_body"] = _bounded_body(
                        sanitized_response_body,
                        max_chars=self.max_body_chars,
                    )
            self._calls.append(entry)
        except Exception as exc:
            self._calls.append(
                {
                    "capture_error": exc.__class__.__name__,
                    "timestamp": time.time(),
                }
            )

    @property
    def entries(self) -> list[dict[str, Any]]:
        return list(self._calls)

    def save(self, output_path: str | Path) -> Path:
        """Write the captured network snapshot to ``output_path``.

        The output format is compatible with ``api_discovery_normalizer``.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {"log": {"entries": self._calls}}
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return output_path

    def clear(self) -> None:
        self._calls.clear()


def _request_body(request: Any) -> Any:
    if request is None:
        return None
    for attribute in ("post_data", "post_data_buffer"):
        value = getattr(request, attribute, None)
        if callable(value):
            try:
                value = value()
            except Exception:
                continue
        if value:
            return value
    return None


def _response_body(response: Any) -> Any:
    try:
        return response.text()
    except Exception as text_error:
        last_error = text_error
    try:
        body = response.body()
        if isinstance(body, bytes):
            return body.decode("utf-8", errors="replace")
        return body
    except Exception:
        _ = last_error
        return None


def _json_like(value: Any) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, dict | list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return None


def _bounded_body(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, str):
        return value[:max_chars]
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    if len(serialized) <= max_chars:
        return value
    return serialized[:max_chars]


def _detect_resource_type(url: str, headers: dict[str, str]) -> str:
    """Guess resource type from Content-Type header or URL extension."""
    ct = (headers.get("content-type") or "").lower()
    if ct.startswith("text/html"):
        return "document"
    if ct.startswith("application/json") or ct.startswith("text/json"):
        return "json"
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("text/css"):
        return "stylesheet"
    if ct.startswith("text/javascript") or ct.startswith("application/javascript"):
        return "script"
    if ct.startswith("application/xml") or ct.startswith("text/xml"):
        return "xml"
    ext = Path(url.split("?")[0]).suffix.lower()
    static_ext = {
        ".js": "script",
        ".css": "stylesheet",
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".gif": "image",
        ".svg": "image",
        ".webp": "image",
        ".ico": "image",
        ".woff": "font",
        ".woff2": "font",
        ".ttf": "font",
    }
    return static_ext.get(ext, "xhr")
