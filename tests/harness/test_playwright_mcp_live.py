from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from harness.infrastructure.mcp.playwright import (
    PlaywrightMCPConfig,
    SynchronousOfficialMCPClient,
)
from harness.infrastructure.tools.playwright_network import inspect_playwright_network

LIVE_MCP_ENABLED = os.environ.get("AGENTIC_QA_PLAYWRIGHT_MCP_LIVE") == "1"
TEST_SECRETS = {
    "query-smoke-secret",
    "header-smoke-secret",
    "body-smoke-secret",
    "response-smoke-secret",
    "13800138000",
}


class _SmokeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/":
            self.send_error(404)
            return
        body = b"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>API discovery smoke</title></head>
<body>
  <button id="discover">Discover API</button>
  <output id="result"></output>
  <script>
    document.querySelector('#discover').addEventListener('click', async () => {
      const response = await fetch('/api/activities/123/assist?token=query-smoke-secret', {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'authorization': 'Bearer header-smoke-secret'
        },
        body: JSON.stringify({
          activity_id: 123,
          phone: '13800138000',
          token: 'body-smoke-secret'
        })
      });
      await response.json();
      document.querySelector('#result').textContent = 'Captured';
    });
  </script>
</body>
</html>"""
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not self.path.startswith("/api/activities/123/assist"):
            self.send_error(404)
            return
        self.rfile.read(int(self.headers.get("content-length") or 0))
        body = json.dumps({"accepted": True, "access_token": "response-smoke-secret"}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("set-cookie", "sid=response-smoke-secret")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _mcp_text(result: dict[str, Any]) -> str:
    return "\n".join(
        str(item.get("text") or "")
        for item in result.get("content") or []
        if isinstance(item, dict) and item.get("type") == "text"
    )


@pytest.mark.playwright_mcp_live
@pytest.mark.skipif(
    not LIVE_MCP_ENABLED,
    reason="set AGENTIC_QA_PLAYWRIGHT_MCP_LIVE=1 to run the official MCP smoke test",
)
def test_official_playwright_mcp_captures_and_redacts_live_api(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SmokeHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    output_dir = Path(
        os.environ.get("AGENTIC_QA_PLAYWRIGHT_MCP_OUTPUT_DIR") or tmp_path / "mcp-output"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    config = PlaywrightMCPConfig(
        transport="stdio",
        command="npx",
        args=(
            "-y",
            "@playwright/mcp@latest",
            "--isolated",
            "--headless",
            "--block-service-workers",
            "--output-dir",
            str(output_dir),
        ),
        allowlist=frozenset(
            {
                "browser_navigate",
                "browser_find",
                "browser_click",
                "browser_network_requests",
                "browser_network_request",
            }
        ),
        request_timeout_seconds=60,
    )
    try:
        with SynchronousOfficialMCPClient(config) as client:
            client.call("browser_navigate", {"url": base_url})
            found = _mcp_text(client.call("browser_find", {"text": "Discover API"}))
            match = re.search(r'button "Discover API" \[ref=([^\]]+)]', found)
            assert match is not None, found
            client.call("browser_click", {"target": match.group(1)})

            for _ in range(20):
                observed = _mcp_text(client.call("browser_find", {"text": "Captured"}))
                if 'Found 1 match for "Captured"' in observed:
                    break
                time.sleep(0.1)
            else:
                pytest.fail("the local API action did not complete")

            catalog = inspect_playwright_network(
                lambda request: client.call(request["tool"], request["arguments"]),
                max_requests=25,
                source="runtime/playwright-network-capture/ci-smoke",
            )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    assert catalog.observed_call_count == 1
    assert catalog.business_candidate_count == 1
    candidate = catalog.candidates[0]
    assert candidate.method == "POST"
    assert candidate.origin == base_url
    assert candidate.path == "/api/activities/{id}/assist"
    assert candidate.status_codes == [200]
    assert set(candidate.request_schema["properties"]) == {"activity_id", "phone", "token"}
    assert set(candidate.response_schema["properties"]) == {"accepted", "access_token"}
    rendered = catalog.model_dump_json()
    assert not any(secret in rendered for secret in TEST_SECRETS)
