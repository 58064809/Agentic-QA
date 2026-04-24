from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable


SkillCallable = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class SkillSpec:
    name: str
    module_path: str
    attribute: str


DEFAULT_SKILL_MODULE = "actions"


def _default_spec(skill_name: str) -> SkillSpec:
    # Convention: actions/<skill_name>.py defines function <skill_name>.
    return SkillSpec(
        name=skill_name,
        module_path=f"{DEFAULT_SKILL_MODULE}.{skill_name}",
        attribute=skill_name,
    )


@lru_cache(maxsize=256)
def _load_skill_callable(spec: SkillSpec) -> SkillCallable | None:
    try:
        module = importlib.import_module(spec.module_path)
    except ModuleNotFoundError:
        return None

    skill = getattr(module, spec.attribute, None)
    return skill if callable(skill) else None


def get_skill(skill_name: str) -> SkillCallable | None:
    return _load_skill_callable(_default_spec(skill_name))
