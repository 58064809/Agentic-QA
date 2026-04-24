from __future__ import annotations

from typing import Any


def parse_env_text(env_text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in env_text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#") or ":" not in raw_line:
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        key, raw_value = raw_line.strip().split(":", 1)
        value = _parse_scalar(raw_value.strip())

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = value
    return root


def flatten_env_config(value: dict[str, Any]) -> dict[str, Any]:
    auth = _section(value, "auth")
    database = _section(value, "database")
    environment = _section(value, "environment")
    return {
        "base_url": environment.get("base_url") or value.get("base_url") or "",
        "api_base_url": environment.get("api_base_url") or value.get("api_base_url") or "",
        "token": auth.get("token") or value.get("token") or "",
        "token_env": auth.get("token_env") or value.get("token_env") or "",
        "token_type": auth.get("token_type") or value.get("token_type") or "Bearer",
        "db_engine": database.get("db_engine") or value.get("db_engine") or "",
        "pg_dsn": database.get("pg_dsn") or value.get("pg_dsn") or "",
        "pg_dsn_env": database.get("pg_dsn_env") or value.get("pg_dsn_env") or "",
        "sqlite_path": database.get("sqlite_path") or value.get("sqlite_path") or "",
    }


def parse_and_flatten_env_text(env_text: str) -> dict[str, Any]:
    return flatten_env_config(parse_env_text(env_text))


def _section(value: dict[str, Any], key: str) -> dict[str, Any]:
    section = value.get(key)
    return section if isinstance(section, dict) else {}


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    value = value.strip().strip('"').strip("'")
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return value
