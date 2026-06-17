"""Session 生命周期管理"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.session.store import (
    SESSION_ID_DEFAULT,
    SessionMetadata,
    SessionStore,
)


class Session:
    """单个会话：持有元数据、checkpointer 路径、历史。"""

    def __init__(self, meta: SessionMetadata, store: SessionStore) -> None:
        self.meta = meta
        self.store = store
        self._history: list[dict[str, str]] | None = None

    @property
    def session_id(self) -> str:
        return self.meta.session_id

    @property
    def thread_id(self) -> str:
        return self.meta.thread_id

    @property
    def checkpoint_db_path(self) -> str:
        return self.store.checkpoint_db_path(self.session_id)

    @property
    def has_history(self) -> bool:
        return self.meta.history_count > 0

    def update_meta(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            if hasattr(self.meta, k):
                setattr(self.meta, k, v)
        from datetime import datetime, timezone

        self.meta.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.save_metadata(self.meta)

    def append_history(self, role: str, content: str) -> None:
        self.store.append_history(self.session_id, role, content)
        self.meta.history_count += 1
        self.store.save_metadata(self.meta)

    def load_history(self, max_lines: int = 20) -> list[dict[str, str]]:
        if self._history is None:
            self._history = self.store.load_history(self.session_id, max_lines=max_lines)
        return self._history

    def reset(self) -> None:
        """清空会话状态（保留 session_id）。"""
        self.store.delete_session(self.session_id)
        self.meta = SessionMetadata.new(self.session_id)
        self._history = None


class SessionManager:
    """外部接口：get_or_create / reset / get"""

    def __init__(self, repo_root: Path | None = None) -> None:
        root = repo_root or Path.cwd()
        self.store = SessionStore(root)

    def get_or_create(self, session_id: str = SESSION_ID_DEFAULT) -> Session:
        meta = self.store.load_metadata(session_id)
        if meta is None:
            meta = SessionMetadata.new(session_id)
            self.store.save_metadata(meta)
        return Session(meta, self.store)

    def reset(self, session_id: str = SESSION_ID_DEFAULT) -> Session:
        self.store.delete_session(session_id)
        return self.get_or_create(session_id)

    def exists(self, session_id: str = SESSION_ID_DEFAULT) -> bool:
        return self.store.session_exists(session_id)
