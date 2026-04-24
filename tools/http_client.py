from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from tools.auth_provider import AuthProvider


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: str
    json: Any
    headers: dict[str, str]


class HttpClient:
    def __init__(self, base_url: str = "", auth_provider: AuthProvider | None = None, timeout_seconds: int = 10) -> None:
        self.base_url = base_url
        self.auth_provider = auth_provider or AuthProvider()
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any = None,
        expected_status: int | None = None,
        auth: str | dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
        retries: int = 0,
    ) -> HttpResponse:
        merged_headers = dict(headers or {})
        if auth:
            merged_headers.update(self.auth_provider.auth_headers(auth))
        data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        if data is not None:
            merged_headers.setdefault("Content-Type", "application/json")

        url = urllib.parse.urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))
        attempts = retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = self._send(method, url, merged_headers, data, timeout_seconds or self.timeout_seconds)
                if expected_status is not None and response.status_code != expected_status:
                    raise AssertionError(
                        f"expected HTTP {expected_status}, got {response.status_code}; body={response.body[:500]}"
                    )
                return response
            except (urllib.error.URLError, OSError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    raise
                time.sleep(0.2 * (attempt + 1))
        raise RuntimeError(f"HTTP request failed: {last_error}")

    def _send(self, method: str, url: str, headers: dict[str, str], data: bytes | None, timeout_seconds: int) -> HttpResponse:
        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
                return HttpResponse(response.status, body, _try_json(body), dict(response.headers))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return HttpResponse(exc.code, body, _try_json(body), dict(exc.headers))


def _try_json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None
