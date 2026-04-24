import json
import sqlite3
import threading
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from pathlib import Path

from actions.case_binding import apply_auto_bindings
from actions.case_binding import execute_case_binding


def test_apply_auto_bindings_marks_deposit_cases_ready() -> None:
    plan = {
        "cases": [
            {"case_id": "DEP-P0-002", "binding": {"status": "pending"}},
            {"case_id": "DEP-P0-001", "binding": {"status": "pending"}},
        ]
    }

    result = apply_auto_bindings(plan, "deposit-management")

    assert result["ready_count"] == 1
    assert result["pending_count"] == 1
    assert result["cases"][0]["binding"]["status"] == "ready"
    assert result["cases"][0]["binding"]["type"] == "python_adapter"


def test_execute_deposit_python_adapter_binding() -> None:
    plan = {"cases": [{"case_id": "DEP-P0-010", "binding": {"status": "pending"}}]}
    case = apply_auto_bindings(plan, "deposit-management")["cases"][0]

    result = execute_case_binding(case)

    assert result["status"] == "passed"
    assert len(result["details"]) == 5


def test_execute_api_flow_binding_with_cleanup() -> None:
    seen_paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen_paths.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if self.path == "/prepare":
                payload = {"success": True, "data": {"id": "case-1"}}
            else:
                payload = {"success": True}
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def do_DELETE(self):
            seen_paths.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"success": true}')

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        case = {
            "case_id": "API-001",
            "binding": {
                "status": "ready",
                "type": "api_flow",
                "steps": [
                    {
                        "name": "prepare",
                        "method": "POST",
                        "path": "/prepare",
                        "expected_status": 200,
                        "assertions": [{"type": "json_equals", "path": "$.success", "expected": True}],
                    },
                    {
                        "name": "execute",
                        "method": "POST",
                        "path": "/business/{{prepare.json.data.id}}",
                        "expected_status": 200,
                    },
                ],
                "cleanup": [
                    {
                        "name": "cleanup",
                        "method": "DELETE",
                        "path": "/data/{{prepare.json.data.id}}",
                        "expected_status": 200,
                    }
                ],
            },
        }

        result = execute_case_binding(case, {"api_base_url": base_url})

        assert result["status"] == "passed"
        assert seen_paths == ["/prepare", "/business/case-1", "/data/case-1"]
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_api_binding_uses_plaintext_token_from_project_env() -> None:
    seen: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["authorization"] = self.headers.get("Authorization", "")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"success": true}')

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        case = {
            "case_id": "API-PLAIN-TOKEN",
            "binding": {
                "status": "ready",
                "type": "api",
                "method": "POST",
                "path": "/demo",
                "expected_status": 200,
            },
        }
        env_text = f"""
environment:
  api_base_url: "{base_url}"
auth:
  token: "plain-token"
  token_env: ""
"""

        result = execute_case_binding(case, {"env_text": env_text})

        assert result["status"] == "passed"
        assert seen["authorization"] == "Bearer plain-token"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_api_binding_renders_custom_header_from_env_text() -> None:
    seen: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["accesstoken"] = self.headers.get("accesstoken", "")
            seen["environment"] = self.headers.get("environment", "")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"success": true}')

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        case = {
            "case_id": "API-CUSTOM-HEADER",
            "binding": {
                "status": "ready",
                "type": "api",
                "method": "GET",
                "path": "/demo",
                "headers": {
                    "accesstoken": "{{env.auth.token}}",
                    "environment": "{{env.headers.environment}}",
                },
                "expected_status": 200,
            },
        }
        env_text = f"""
environment:
  api_base_url: "{base_url}"
auth:
  token: "custom-header-token"
headers:
  environment: "1"
"""

        result = execute_case_binding(case, {"env_text": env_text})

        assert result["status"] == "passed"
        assert seen["accesstoken"] == "custom-header-token"
        assert seen["environment"] == "1"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_api_binding_uses_named_profile_defaults() -> None:
    seen: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length:
                self.rfile.read(content_length)
            seen["accesstoken"] = self.headers.get("accesstoken", "")
            seen["cookie"] = self.headers.get("Cookie", "")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"success": true}')

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        case = {
            "case_id": "API-PROFILE-DEFAULTS",
            "binding": {
                "status": "ready",
                "type": "api",
                "profile": "platform_admin",
                "method": "POST",
                "path": "/demo",
                "json": {"ok": True},
                "expected_status": 200,
            },
        }
        env_text = f"""
environment:
  active_profile: "merchant_admin"
profiles:
  platform_admin:
    environment:
      api_base_url: "{base_url}"
    auth:
      mode: "header"
      token: "profile-token"
      header_name: "accesstoken"
    cookies:
      session_id: "cookie-1"
"""

        result = execute_case_binding(case, {"env_text": env_text})

        assert result["status"] == "passed"
        assert seen["accesstoken"] == "profile-token"
        assert seen["cookie"] == "session_id=cookie-1"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_execute_data_driven_scenario_binding(monkeypatch) -> None:
    seen_requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
            seen_requests.append({"method": "POST", "path": self.path, "body": json.loads(body)})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if self.path == "/prepare":
                payload = {"success": True, "data": {"merchant_id": "merchant-from-prepare"}}
            else:
                payload = {"success": True, "data": {"applyId": "apply-1"}}
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def do_DELETE(self):
            seen_requests.append({"method": "DELETE", "path": self.path})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"success": true}')

        def log_message(self, format, *args):
            return

    def fake_db_assert(case, env):
        assert case["binding"]["assertions"][0]["params"] == ["REQ123"]
        return {"status": "passed", "case_id": case["case_id"], "db_assertions": [{"row_count": 1}]}

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr("actions.case_binding._execute_db_assert_binding", fake_db_assert)
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        case = {
            "case_id": "SCN-001",
            "binding": {
                "status": "ready",
                "type": "scenario",
                "data": {"merchant_id": "merchant-1", "amount": 1000},
                "generators": {"request_no": {"type": "fixed", "value": "REQ123"}, "scene_id": {"type": "fixed", "value": "SCENE1"}},
                "steps": [
                    {
                        "name": "prepare",
                        "method": "POST",
                        "path": "/prepare",
                        "json": {"merchantId": "{{data.merchant_id}}", "sceneId": "{{gen.scene_id}}"},
                        "expected_status": 200,
                    },
                    {
                        "name": "submit",
                        "method": "POST",
                        "path": "/deposit/{{prepare.json.data.merchant_id}}",
                        "json": {"requestNo": "{{gen.request_no}}", "amount": "{{data.amount}}"},
                        "expected_status": 200,
                    },
                ],
                "db_assertions": [
                    {
                        "query": "select count(*) from deposit_order where request_no = %s",
                        "params": ["{{gen.request_no}}"],
                        "expected_first_value": 1,
                    }
                ],
                "cleanup": [
                    {"name": "cleanup", "method": "DELETE", "path": "/scene/{{gen.scene_id}}", "expected_status": 200}
                ],
            },
        }

        result = execute_case_binding(case, {"api_base_url": base_url})

        assert result["status"] == "passed"
        assert seen_requests[0]["body"] == {"merchantId": "merchant-1", "sceneId": "SCENE1"}
        assert seen_requests[1]["path"] == "/deposit/merchant-from-prepare"
        assert seen_requests[1]["body"] == {"requestNo": "REQ123", "amount": 1000}
        assert seen_requests[2]["path"] == "/scene/SCENE1"
        assert result["db_assertions"] == [{"row_count": 1}]
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_execute_db_assert_binding_with_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("create table deposit_order(id text primary key, status text)")
        connection.execute("insert into deposit_order values('order-1', 'PAID')")
        connection.commit()
    finally:
        connection.close()

    case = {
        "case_id": "DB-001",
        "binding": {
            "status": "ready",
            "type": "db_assert",
            "sqlite_path": str(db_path),
            "assertions": [
                {
                    "query": "select status from deposit_order where id = ?",
                    "params": ["order-1"],
                    "expected_first_value": "PAID",
                }
            ],
        },
    }

    result = execute_case_binding(case)

    assert result["status"] == "passed"
    assert result["db_assertions"][0]["row_count"] == 1


def test_execute_db_assert_binding_with_postgres_driver(monkeypatch) -> None:
    executed: dict[str, object] = {}

    class FakeCursor:
        def execute(self, query, params):
            executed["query"] = query
            executed["params"] = params

        def fetchall(self):
            return [(1,)]

        def close(self):
            executed["cursor_closed"] = True

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            executed["connection_closed"] = True

    def fake_import_module(name: str):
        if name == "psycopg":
            return SimpleNamespace(connect=lambda dsn, autocommit=True: FakeConnection())
        raise ImportError(name)

    monkeypatch.setattr("tools.pg_client.importlib.import_module", fake_import_module)
    monkeypatch.setenv("TEST_PG_DSN", "postgresql://readonly:secret@example:5432/app")
    case = {
        "case_id": "PG-001",
        "binding": {
            "status": "ready",
            "type": "db_assert",
            "engine": "postgres",
            "dsn_env": "TEST_PG_DSN",
            "assertions": [
                {
                    "query": "select count(*) from deposit_order where id = %s",
                    "params": ["order-1"],
                    "expected_first_value": 1,
                }
            ],
        },
    }

    result = execute_case_binding(case)

    assert result["status"] == "passed"
    assert executed["query"] == "select count(*) from deposit_order where id = %s"
    assert executed["params"] == ["order-1"]
    assert executed["cursor_closed"] is True
    assert executed["connection_closed"] is True


def test_execute_db_assert_binding_with_plaintext_pg_dsn(monkeypatch) -> None:
    executed: dict[str, object] = {}

    class FakeCursor:
        def execute(self, query, params):
            executed["query"] = query
            executed["params"] = params

        def fetchall(self):
            return [(1,)]

        def close(self):
            pass

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    def fake_import_module(name: str):
        if name == "psycopg":
            return SimpleNamespace(connect=lambda dsn, autocommit=True: FakeConnection())
        raise ImportError(name)

    monkeypatch.setattr("tools.pg_client.importlib.import_module", fake_import_module)
    case = {
        "case_id": "PG-PLAIN",
        "binding": {
            "status": "ready",
            "type": "db_assert",
            "assertions": [{"query": "select 1", "expected_first_value": 1}],
        },
    }
    env_text = """
database:
  db_engine: "postgres"
  pg_dsn: "postgresql://readonly:secret@example:5432/app"
"""

    result = execute_case_binding(case, {"env_text": env_text})

    assert result["status"] == "passed"
    assert executed["query"] == "select 1"
