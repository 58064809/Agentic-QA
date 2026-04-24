from __future__ import annotations

import importlib
import os
from typing import Any


class PgReadonlyClient:
    def __init__(self, dsn: str = "", dsn_env: str = "TEST_PG_DSN") -> None:
        self.dsn = dsn or os.getenv(dsn_env, "")
        if not self.dsn:
            raise AssertionError(f"Postgres DSN is missing; set {dsn_env}")

    def query(self, sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> list[tuple[Any, ...]]:
        _assert_readonly_sql(sql)
        connection = _connect_postgres(self.dsn)
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(sql, params or [])
                return list(cursor.fetchall())
            finally:
                close = getattr(cursor, "close", None)
                if callable(close):
                    close()
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()


def _connect_postgres(dsn: str):
    try:
        psycopg = importlib.import_module("psycopg")
        return psycopg.connect(dsn, autocommit=True)
    except ImportError:
        try:
            psycopg2 = importlib.import_module("psycopg2")
            connection = psycopg2.connect(dsn)
            connection.autocommit = True
            return connection
        except ImportError as exc:
            raise AssertionError("postgres requires installing psycopg or psycopg2") from exc


def _assert_readonly_sql(sql: str) -> None:
    lowered = sql.lower().strip()
    if not lowered.startswith("select"):
        raise AssertionError("PG client only allows SELECT queries")
    forbidden = (" insert ", " update ", " delete ", " drop ", " alter ", " truncate ", " create ")
    padded = f" {lowered} "
    if any(keyword in padded for keyword in forbidden):
        raise AssertionError("PG client query is not readonly")
