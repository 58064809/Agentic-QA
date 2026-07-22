from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from harness.domain.models import AgentManifest, SkillManifest, ToolManifest

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
        package_root = Path(__file__).parents[2]
        return cls(
            _load_manifests(package_root / "manifests" / "agents", AgentManifest),
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
        package_root = Path(__file__).parents[2]
        return cls(_load_manifests(package_root / "manifests" / "tools", ToolManifest))

    def get(self, name: str) -> ToolManifest:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def list(self) -> list[ToolManifest]:
        return list(self._items.values())


class SkillRegistry:
    def __init__(
        self,
        manifests: dict[str, SkillManifest],
        *,
        knowledge_root: Path | None = None,
    ):
        self._items = dict(manifests)
        self._knowledge_root = knowledge_root.resolve() if knowledge_root else None
        self._instructions = {
            name: self._compile_instructions(item) for name, item in self._items.items()
        }

    @classmethod
    def builtin(cls) -> SkillRegistry:
        package_root = Path(__file__).parents[2]
        return cls(
            _load_manifests(package_root / "manifests" / "skills", SkillManifest),
            knowledge_root=package_root / "knowledge",
        )

    def _compile_instructions(self, manifest: SkillManifest) -> str:
        sections = [manifest.instructions.strip()]
        for reference in manifest.references:
            if self._knowledge_root is None:
                raise ValueError(f"skill {manifest.name} references knowledge without a root")
            target = (self._knowledge_root / reference).resolve()
            if not target.is_relative_to(self._knowledge_root):
                raise ValueError(
                    f"skill {manifest.name} knowledge path escapes package: {reference}"
                )
            if not target.is_file():
                raise ValueError(f"skill {manifest.name} knowledge file is missing: {reference}")
            text = target.read_text(encoding="utf-8").strip()
            if not text:
                raise ValueError(f"skill {manifest.name} knowledge file is empty: {reference}")
            sections.append(f"参考知识：{reference}\n{text}")
        compiled = "\n\n".join(sections)
        if len(compiled) > 50_000:
            raise ValueError(f"skill {manifest.name} compiled instructions exceed 50000 characters")
        return compiled

    def get(self, name: str) -> SkillManifest:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"unknown skill: {name}") from exc

    def list(self) -> list[SkillManifest]:
        return list(self._items.values())

    def instructions(self, name: str) -> str:
        self.get(name)
        return self._instructions[name]
