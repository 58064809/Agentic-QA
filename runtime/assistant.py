from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.router import handle_user_input


class PersonalAITestAssistant:
    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = Path(workspace_root) if workspace_root else None

    def handle(self, user_text: str) -> dict[str, Any]:
        return handle_user_input(user_text, workspace_root=self.workspace_root)
