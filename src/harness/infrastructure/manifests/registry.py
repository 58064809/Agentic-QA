from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel

from harness.domain.models import (
    AgentPromptManifest,
    KnowledgeSpec,
    PhasePromptManifest,
    SkillPromptManifest,
    ToolManifest,
)

T = TypeVar("T", bound=BaseModel)


def _load_manifests(path: Path, model: type[T]) -> dict[str, T]:
    result: dict[str, T] = {}
    for manifest_path in sorted(path.glob("*.yml")):
        payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        item = model.model_validate(payload)
        if manifest_path.stem != item.name:
            raise ValueError(
                f"manifest filename must match name: {manifest_path.name} != {item.name}"
            )
        if item.name in result:
            raise ValueError(f"duplicate manifest: {item.name}")
        result[item.name] = item
    return result


class AgentRegistry:
    def __init__(
        self,
        manifests: dict[str, AgentPromptManifest],
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
            _load_manifests(package_root / "manifests" / "agents", AgentPromptManifest),
            skills=skills,
            tools=tools,
        )

    def get(self, name: str) -> AgentPromptManifest:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"unknown agent: {name}") from exc

    def list(self) -> list[AgentPromptManifest]:
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
        manifests: dict[str, SkillPromptManifest],
        *,
        knowledge: KnowledgeRegistry | None = None,
    ):
        self._items = dict(manifests)
        self.knowledge = knowledge or KnowledgeRegistry({})
        for manifest in self._items.values():
            for reference in manifest.knowledge_refs:
                knowledge_spec = self.knowledge.get(reference)
                if manifest.name not in knowledge_spec.applies_to:
                    raise ValueError(
                        f"knowledge {reference} does not apply to skill {manifest.name}"
                    )

    @classmethod
    def builtin(cls) -> SkillRegistry:
        package_root = Path(__file__).parents[2]
        return cls(
            _load_manifests(package_root / "manifests" / "skills", SkillPromptManifest),
            knowledge=KnowledgeRegistry.builtin(),
        )

    def get(self, name: str) -> SkillPromptManifest:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"unknown skill: {name}") from exc

    def list(self) -> list[SkillPromptManifest]:
        return list(self._items.values())

    def knowledge_for(self, name: str) -> list[KnowledgeSpec]:
        manifest = self.get(name)
        return [self.knowledge.get(reference) for reference in manifest.knowledge_refs]


class KnowledgeRegistry:
    def __init__(self, specs: dict[str, KnowledgeSpec]):
        self._items = dict(specs)

    @classmethod
    def builtin(cls) -> KnowledgeRegistry:
        package_root = Path(__file__).parents[2]
        return cls(_load_manifests(package_root / "knowledge", KnowledgeSpec))

    def get(self, name: str) -> KnowledgeSpec:
        try:
            return self._items[name]
        except KeyError as exc:
            raise KeyError(f"unknown knowledge: {name}") from exc

    def list(self) -> list[KnowledgeSpec]:
        return list(self._items.values())


class PhasePromptRegistry:
    def __init__(self, manifests: dict[str, PhasePromptManifest]):
        self._items = dict(manifests)

    @classmethod
    def builtin(cls) -> PhasePromptRegistry:
        package_root = Path(__file__).parents[2]
        return cls(_load_manifests(package_root / "manifests" / "prompts", PhasePromptManifest))

    def get(self, name: str, *, agent: str | None = None) -> PhasePromptManifest:
        try:
            manifest = self._items[name]
        except KeyError as exc:
            raise KeyError(f"unknown prompt phase: {name}") from exc
        if agent is not None and agent not in manifest.agents:
            raise ValueError(f"prompt phase {name} does not support agent {agent}")
        return manifest

    def list(self) -> list[PhasePromptManifest]:
        return list(self._items.values())
