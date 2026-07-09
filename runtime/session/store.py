"""Session persistence backed by LangGraph Store."""

from __future__ import annotations

import os
import uuid
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

SESSION_ID_DEFAULT = "default"
STORE_DSN_ENV = "AGENTIC_QA_STORE_POSTGRES_DSN"
SESSION_NAMESPACE_ROOT = ("agentic-qa", "sessions")
METADATA_KEY = "metadata"


@dataclass
class SessionMetadata:
    session_id: str = SESSION_ID_DEFAULT
    thread_id: str = ""
    last_prd_path: str | None = None
    last_intent: str | None = None
    history_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def new(cls, session_id: str = SESSION_ID_DEFAULT) -> SessionMetadata:
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            session_id=session_id,
            thread_id=f"thread_{uuid.uuid4().hex[:12]}",
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionMetadata:
        return cls(**data)


class SessionStore:
    """Manage session metadata and history through LangGraph Store."""

    def __init__(self, base_dir: Path, store: BaseStore | None = None) -> None:
        self.base_dir = base_dir
        self._store_context: AbstractContextManager[BaseStore] | None = None
        self.store = store or self._default_store()

    # ── LangGraph Store namespaces ────────────────────────────

    def metadata_namespace(self, session_id: str) -> tuple[str, ...]:
        return (*SESSION_NAMESPACE_ROOT, session_id, "metadata")

    def history_namespace(self, session_id: str) -> tuple[str, ...]:
        return (*SESSION_NAMESPACE_ROOT, session_id, "history")

    # ── 元数据读写 ───────────────────────────────────────────

    def load_metadata(self, session_id: str) -> SessionMetadata | None:
        item = self.store.get(self.metadata_namespace(session_id), METADATA_KEY)
        if item is None:
            return None
        try:
            return SessionMetadata.from_dict(dict(item.value))
        except (KeyError, TypeError):
            return None

    def save_metadata(self, meta: SessionMetadata) -> None:
        self.store.put(self.metadata_namespace(meta.session_id), METADATA_KEY, meta.to_dict())

    def delete_session(self, session_id: str) -> None:
        self.store.delete(self.metadata_namespace(session_id), METADATA_KEY)
        self._delete_namespace_items(self.history_namespace(session_id))

    def session_exists(self, session_id: str) -> bool:
        return self.store.get(self.metadata_namespace(session_id), METADATA_KEY) is not None

    def append_history(self, session_id: str, role: str, content: str) -> None:
        """Append one message to the session history collection."""
        meta = self.load_metadata(session_id)
        sequence = (meta.history_count if meta else 0) + 1
        timestamp = datetime.now(timezone.utc).isoformat()
        key = f"{sequence:012d}-{uuid.uuid4().hex[:8]}"
        self.store.put(
            self.history_namespace(session_id),
            key,
            {
                "role": role,
                "content": content,
                "timestamp": timestamp,
                "sequence": sequence,
            },
        )

    def load_history(self, session_id: str, max_lines: int = 50) -> list[dict[str, str]]:
        """Load recent session history from LangGraph Store."""
        items = self.store.search(
            self.history_namespace(session_id),
            limit=max(max_lines, 1000),
        )
        values = [dict(item.value) for item in items]
        values.sort(key=lambda item: int(item.get("sequence") or 0))
        return [
            {
                "role": str(item.get("role") or ""),
                "content": str(item.get("content") or ""),
                "timestamp": str(item.get("timestamp") or ""),
            }
            for item in values[-max_lines:]
        ]

    def close(self) -> None:
        if self._store_context is not None:
            self._store_context.__exit__(None, None, None)
            self._store_context = None

    def _default_store(self) -> BaseStore:
        dsn = os.getenv(STORE_DSN_ENV)
        if not dsn:
            return InMemoryStore()
        try:
            from langgraph.store.postgres import PostgresStore
        except ImportError:
            return InMemoryStore()
        context = PostgresStore.from_conn_string(dsn)
        store = context.__enter__()
        store.setup()
        self._store_context = context
        return store

    def _delete_namespace_items(self, namespace: tuple[str, ...]) -> None:
        while True:
            items = self.store.search(namespace, limit=100)
            if not items:
                return
            for item in items:
                self.store.delete(namespace, item.key)
