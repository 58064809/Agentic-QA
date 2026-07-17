from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from harness.contracts import AgentManifest, SkillManifest, ToolManifest

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
    def __init__(
        self,
        manifests: dict[str, AgentManifest],
        *,
        skills: SkillRegistry | None = None,
        tools: ToolRegistry | None = None,
    ):
        self._items = dict(manifests)
        if "qa_supervisor" not in self._items:
            raise ValueError("qa_supervisor manifest is required")
        if skills is not None:
            for agent in self._items.values():
                for skill in agent.skills:
                    skills.get(skill)
        if tools is not None:
            for agent in self._items.values():
                for tool in agent.tool_allowlist:
                    tools.get(tool)

    @classmethod
    def builtin(
        cls,
        *,
        skills: SkillRegistry | None = None,
        tools: ToolRegistry | None = None,
    ) -> AgentRegistry:
        skills = skills or SkillRegistry.builtin()
        tools = tools or ToolRegistry.builtin()
        return cls(
            _load_manifests(Path(__file__).parent / "manifests" / "agents", AgentManifest),
            skills=skills,
            tools=tools,
        )

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


class SkillRegistry:
    def __init__(self, manifests: dict[str, SkillManifest]):
        self._items = dict(manifests)

    @classmethod
    def builtin(cls) -> SkillRegistry:
        return cls(_load_manifests(Path(__file__).parent / "manifests" / "skills", SkillManifest))

    def get(self, name: str) -> SkillManifest:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"unknown skill: {name}") from exc

    def list(self) -> list[SkillManifest]:
        return list(self._items.values())
