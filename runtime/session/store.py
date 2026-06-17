"""Session 持久化管理：元数据 + LangGraph SqliteSaver"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SESSION_ID_DEFAULT = "default"
SESSIONS_DIR = ".runtime/sessions"


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
    """管理 session 元数据文件和 SqliteSaver 数据库文件的路径与读写。"""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    # ── 路径 ─────────────────────────────────────────────────

    def session_dir(self, session_id: str) -> Path:
        return self.base_dir / SESSIONS_DIR / session_id

    def metadata_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "metadata.json"

    def checkpoint_db_path(self, session_id: str) -> str:
        """返回 SqliteSaver 使用的数据库文件路径（str）。"""
        path = self.session_dir(session_id) / "checkpoints.db"
        return str(path)

    # ── 元数据读写 ───────────────────────────────────────────

    def load_metadata(self, session_id: str) -> SessionMetadata | None:
        path = self.metadata_path(session_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return SessionMetadata.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def save_metadata(self, meta: SessionMetadata) -> None:
        path = self.metadata_path(meta.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(meta.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def delete_session(self, session_id: str) -> None:
        sdir = self.session_dir(session_id)
        if sdir.is_dir():
            import shutil

            shutil.rmtree(sdir)

    def session_exists(self, session_id: str) -> bool:
        return self.metadata_path(session_id).is_file()

    def append_history(self, session_id: str, role: str, content: str) -> None:
        """追加一条历史记录到 history.jsonl。"""
        path = self.session_dir(session_id) / "history.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = json.dumps(
            {"role": role, "content": content, "timestamp": datetime.now(timezone.utc).isoformat()},
            ensure_ascii=False,
        )
        with path.open("a", encoding="utf-8") as f:
            f.write(entry + "\n")

    def load_history(self, session_id: str, max_lines: int = 50) -> list[dict[str, str]]:
        """加载最近的历史记录。"""
        path = self.session_dir(session_id) / "history.jsonl"
        if not path.is_file():
            return []
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        history: list[dict[str, str]] = []
        for line in lines[-max_lines:]:
            line = line.strip()
            if line:
                try:
                    history.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return history
