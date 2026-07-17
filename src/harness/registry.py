from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from harness.contracts import AgentManifest, ToolManifest

T = TypeVar("T", bound=BaseModel)


def _load_manifests(path: Path, model: type[T]) -> dict[str, T]:
    result: dict[str, T] = {}
    for manifest_path in sorted(path.glob("*.yml")):
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        item = model.model_validate(payload)
        if item.name in result:
            raise ValueError(f"duplicate manifest: {item.name}")
        result[item.name] = item
    return result


class AgentRegistry:
    def __init__(self, manifests: dict[str, AgentManifest]):
        self._items = dict(manifests)
        if "qa_supervisor" not in self._items:
            raise ValueError("qa_supervisor manifest is required")

    @classmethod
    def builtin(cls) -> AgentRegistry:
        return cls(_load_manifests(Path(__file__).parent / "manifests" / "agents", AgentManifest))

    def get(self, name: str) -> AgentManifest:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"unknown agent: {name}") from exc

    def list(self) -> list[AgentManifest]:
        return list(self._items.values())


class ToolRegistry:
    def __init__(self, manifests: dict[str, ToolManifest]):
        self._items = dict(manifests)

    @classmethod
    def builtin(cls) -> ToolRegistry:
        return cls(_load_manifests(Path(__file__).parent / "manifests" / "tools", ToolManifest))

    def get(self, name: str) -> ToolManifest:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def list(self) -> list[ToolManifest]:
        return list(self._items.values())
