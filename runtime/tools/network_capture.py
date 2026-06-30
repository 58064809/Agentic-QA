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


class NetworkCapture:
    """Listen to Playwright ``page.on("response")`` and build a HAR-like snapshot.

    Call ``on_response(response)`` for every intercepted response, then
    ``save(output_path)`` to persist the snapshot for ``api_discovery``.
    """

    def __init__(self) -> None:
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

            body: str | None = None
            try:
                body = response.text()
            except Exception:
                try:
                    body = response.body()
                    if isinstance(body, bytes):
                        body = body.decode("utf-8", errors="replace")
                except Exception:
                    body = None

            entry = {
                "url": url,
                "method": method,
                "status": status,
                "request_headers": _sanitize_simple(req_headers),
                "response_headers": _sanitize_simple(resp_headers),
                "response_body": body[:50000] if body else None,
                "timestamp": time.time(),
                "resource_type": _detect_resource_type(url, resp_headers),
            }
            self._calls.append(entry)
        except Exception:
            pass  # swallow per-call errors so rest of capture survives

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


def _sanitize_simple(headers: dict[str, str]) -> dict[str, str]:
    """Mask sensitive header values for storage."""
    sensitive = {"authorization", "cookie", "set-cookie", "x-token", "x-api-key", "x-csrf-token"}
    return {k: "<REDACTED>" if k.lower() in sensitive else v for k, v in headers.items()}


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
