from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CheckpointPostgresConfig:
    host_env: str = "PG_LOCAL_HOST"
    port_env: str = "PG_LOCAL_PORT"
    database_env: str = "PG_LOCAL_DATABASE"
    user_env: str = "PG_LOCAL_USER"
    password_env: str = "PG_LOCAL_PASSWORD"
    connect_timeout_seconds: int = 5

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


@contextmanager
def postgres_checkpointer() -> Iterator[Any]:
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.conninfo import make_conninfo

    conninfo = make_conninfo(**CheckpointPostgresConfig().connection_kwargs())
    with PostgresSaver.from_conn_string(conninfo) as checkpointer:
        checkpointer.setup()
        yield checkpointer


class PostgresCheckpointProvider:
    """生产环境唯一 checkpoint provider。"""

    def open(self) -> Any:
        return postgres_checkpointer()
