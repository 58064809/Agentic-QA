from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CheckpointPostgresConfig:
    host: str = "localhost"
    port: int = 5432
    database: str = "postgres"
    user: str = "postgres"
    password: str = ""
    connect_timeout_seconds: int = 5

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


@contextmanager
def postgres_checkpointer(config: CheckpointPostgresConfig) -> Iterator[Any]:
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.conninfo import make_conninfo

    conninfo = make_conninfo(**config.connection_kwargs())
    with PostgresSaver.from_conn_string(conninfo) as checkpointer:
        checkpointer.setup()
        yield checkpointer


class PostgresCheckpointProvider:
    """生产环境唯一 checkpoint provider。"""

    def __init__(self, config: CheckpointPostgresConfig) -> None:
        self._config = config

    def open(self) -> Any:
        return postgres_checkpointer(self._config)
