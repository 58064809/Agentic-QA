from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PostgresSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agentic-qa.harness.postgres-source.v2"] = (
        "agentic-qa.harness.postgres-source.v2"
    )
    host: str = "localhost"
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = "postgres"
    user: str = "postgres"
    password: str = ""
    connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    statement_timeout_ms: int = Field(default=10_000, ge=100, le=60_000)
    max_rows: int = Field(default=200, ge=1, le=1000)

    def connection_kwargs(self) -> dict[str, Any]:
        if not self.password:
            raise RuntimeError("PostgreSQL password is not set in agentic-qa.local.yml")
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
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
