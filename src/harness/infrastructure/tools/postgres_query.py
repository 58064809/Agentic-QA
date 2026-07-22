from __future__ import annotations

import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PostgresSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agentic-qa.harness.postgres-source.v2"] = (
        "agentic-qa.harness.postgres-source.v2"
    )
    host_env: str = "PG_LOCAL_HOST"
    port_env: str = "PG_LOCAL_PORT"
    database_env: str = "PG_LOCAL_DATABASE"
    user_env: str = "PG_LOCAL_USER"
    password_env: str = "PG_LOCAL_PASSWORD"
    connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    statement_timeout_ms: int = Field(default=10_000, ge=100, le=60_000)
    max_rows: int = Field(default=200, ge=1, le=1000)

    def connection_kwargs(self) -> dict[str, Any]:
        password = os.getenv(self.password_env, "")
        if not password:
            raise RuntimeError(
                f"PostgreSQL password environment variable is not set: {self.password_env}"
            )
        return {
            "host": os.getenv(self.host_env, "localhost").strip(),
            "port": os.getenv(self.port_env, "5432").strip(),
            "dbname": os.getenv(self.database_env, "postgres").strip(),
            "user": os.getenv(self.user_env, "postgres").strip(),
            "password": password,
            "connect_timeout": self.connect_timeout_seconds,
        }


_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|merge|create|alter|drop|truncate|grant|revoke|copy|call|do|vacuum|analyze|refresh|reindex|cluster)\b",
    re.IGNORECASE,
)


def execute_read_only_query(
    config: PostgresSourceConfig,
    query: str,
    parameters: list[Any] | None = None,
) -> dict[str, Any]:
    normalized = query.strip()
    if not normalized or not re.match(r"^(select|with)\b", normalized, re.IGNORECASE):
        raise ValueError("postgres.query only accepts SELECT or WITH queries")
    if _FORBIDDEN_SQL.search(normalized):
        raise ValueError("postgres.query rejected a state-changing SQL keyword")
    if ";" in normalized.rstrip(";"):
        raise ValueError("postgres.query accepts exactly one statement")

    import psycopg

    with psycopg.connect(**config.connection_kwargs(), autocommit=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(f"SET LOCAL statement_timeout = {config.statement_timeout_ms}")
            cursor.execute(normalized, parameters or [])
            columns = [item.name for item in cursor.description or []]
            rows = cursor.fetchmany(config.max_rows + 1)
            connection.rollback()
    return {
        "columns": columns,
        "rows": [[_json_safe_cell(cell) for cell in row] for row in rows[: config.max_rows]],
        "row_count": min(len(rows), config.max_rows),
        "truncated": len(rows) > config.max_rows,
    }


def _json_safe_cell(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, bytes):
        return value.hex()
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)
