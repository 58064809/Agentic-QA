from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

API_KEY_ENV = "FREEMODEL_API_KEY"
BASE_URL_ENV = "FREEMODEL_BASE_URL"
MODEL_ENV = "FREEMODEL_MODEL"

DEFAULT_PROVIDER = "openai_compatible"
DEFAULT_BASE_URL = "https://api.freemodel.dev"
DEFAULT_MODEL = "gpt-5.5"


def default_llm_metadata(*, enabled: bool = False) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "used": False,
        "provider": DEFAULT_PROVIDER,
        "base_url": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "calls": 0,
        "errors": [],
    }


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    api_key: str | None
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> OpenAICompatibleConfig:
        env = environ or os.environ
        api_key = env.get(API_KEY_ENV) or None
        base_url = env.get(BASE_URL_ENV) or DEFAULT_BASE_URL
        model = env.get(MODEL_ENV) or DEFAULT_MODEL
        return cls(api_key=api_key, base_url=base_url, model=model)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def to_metadata(self, *, enabled: bool) -> dict[str, Any]:
        metadata = default_llm_metadata(enabled=enabled)
        metadata["base_url"] = self.base_url
        metadata["model"] = self.model
        return metadata
