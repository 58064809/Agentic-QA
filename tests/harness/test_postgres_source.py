from __future__ import annotations

from types import SimpleNamespace

import pytest

from harness.infrastructure.tools.postgres_query import (
    PostgresSourceConfig,
    execute_read_only_query,
)


def test_postgres_config_reads_password_only_from_named_environment(monkeypatch) -> None:
    for name in ("PG_LOCAL_HOST", "PG_LOCAL_PORT", "PG_LOCAL_DATABASE", "PG_LOCAL_USER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PG_LOCAL_PASSWORD", "not-a-real-password")
    config = PostgresSourceConfig()

    values = config.connection_kwargs()

    assert values == {
        "host": "localhost",
        "port": "5432",
        "dbname": "postgres",
        "user": "postgres",
        "password": "not-a-real-password",
        "connect_timeout": 5,
    }


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM users",
        "WITH removed AS (DELETE FROM users RETURNING *) SELECT * FROM removed",
        "SELECT 1; SELECT 2",
    ],
)
def test_postgres_query_rejects_mutation_or_multiple_statements(query: str) -> None:
    with pytest.raises(ValueError):
        execute_read_only_query(PostgresSourceConfig(), query)


def test_postgres_query_uses_read_only_transaction(monkeypatch) -> None:
    executed: list[tuple[str, object]] = []

    class Cursor:
        description = [SimpleNamespace(name="value")]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query, parameters=None):
            executed.append((query, parameters))

        def fetchmany(self, _count):
            return [(1,)]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self):
            return Cursor()

        def rollback(self):
            executed.append(("ROLLBACK", None))

    fake_psycopg = SimpleNamespace(connect=lambda **_kwargs: Connection())
    monkeypatch.setitem(__import__("sys").modules, "psycopg", fake_psycopg)
    monkeypatch.setenv("PG_LOCAL_PASSWORD", "not-a-real-password")

    result = execute_read_only_query(PostgresSourceConfig(), "SELECT %s", [1])

    assert executed == [
        ("SET TRANSACTION READ ONLY", None),
        ("SET LOCAL statement_timeout = 10000", None),
        ("SELECT %s", [1]),
        ("ROLLBACK", None),
    ]
    assert result == {
        "columns": ["value"],
        "rows": [[1]],
        "row_count": 1,
        "truncated": False,
    }
