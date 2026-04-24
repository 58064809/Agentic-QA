import json
import threading
import time
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer

from tools.auth_provider import AuthProvider
from tools.auth_provider import AuthToken
from tools.env_config import parse_and_flatten_env_text
from tools.http_client import HttpClient
from tools.secret_store import SecretStore


def test_secret_store_prefers_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TEST_SECRET_VALUE", "from-env")
    store = SecretStore(tmp_path / "secrets.json", allow_plaintext_fallback=True)
    store.set("TEST_SECRET_VALUE", "from-file")

    assert store.get("TEST_SECRET_VALUE") == "from-env"


def test_auth_provider_uses_env_token(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TEST_AUTH_TOKEN", "token-1")
    provider = AuthProvider(
        secret_store=SecretStore(tmp_path / "secrets.json", allow_plaintext_fallback=True),
        cache_file=tmp_path / "tokens.json",
    )

    assert provider.auth_headers({"token_env": "TEST_AUTH_TOKEN"}) == {"Authorization": "Bearer token-1"}


def test_auth_provider_uses_plaintext_token(tmp_path) -> None:
    provider = AuthProvider(
        secret_store=SecretStore(tmp_path / "secrets.json", allow_plaintext_fallback=True),
        cache_file=tmp_path / "tokens.json",
    )

    assert provider.auth_headers({"token": "plain-token"}) == {"Authorization": "Bearer plain-token"}


def test_auth_provider_uses_unexpired_cached_token(tmp_path) -> None:
    provider = AuthProvider(
        secret_store=SecretStore(tmp_path / "secrets.json", allow_plaintext_fallback=True),
        cache_file=tmp_path / "tokens.json",
    )
    provider.save_token("merchant", AuthToken("cached-token", expires_at=time.time() + 3600))

    assert provider.auth_headers({"name": "merchant"}) == {"Authorization": "Bearer cached-token"}


def test_http_client_injects_auth_header(monkeypatch, tmp_path) -> None:
    seen: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["authorization"] = self.headers.get("Authorization", "")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))

        def log_message(self, format, *args):
            return

    monkeypatch.setenv("TEST_AUTH_TOKEN", "token-1")
    provider = AuthProvider(
        secret_store=SecretStore(tmp_path / "secrets.json", allow_plaintext_fallback=True),
        cache_file=tmp_path / "tokens.json",
    )
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = HttpClient(f"http://127.0.0.1:{server.server_address[1]}", auth_provider=provider)
        response = client.request("POST", "/demo", json_body={"ok": True}, auth={"token_env": "TEST_AUTH_TOKEN"})

        assert response.status_code == 200
        assert response.json == {"success": True}
        assert seen["authorization"] == "Bearer token-1"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_parse_project_env_plaintext_values() -> None:
    config = parse_and_flatten_env_text(
        """
environment:
  base_url: "https://example.test"
  api_base_url: "https://api.example.test"
auth:
  token: "plain-token"
  token_env: ""
database:
  db_engine: "postgres"
  pg_dsn: "postgresql://user:pass@host:5432/db"
"""
    )

    assert config["api_base_url"] == "https://api.example.test"
    assert config["token"] == "plain-token"
    assert config["pg_dsn"] == "postgresql://user:pass@host:5432/db"
