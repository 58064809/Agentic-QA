from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

API_KEY_ENV = "FREEMODEL_API_KEY"
BASE_URL_ENV = "FREEMODEL_BASE_URL"
MODEL_ENV = "FREEMODEL_MODEL"
ENABLE_CHAT_FALLBACK_ENV = "FREEMODEL_ENABLE_CHAT_FALLBACK"
MAX_INPUT_CHARS_ENV = "FREEMODEL_MAX_INPUT_CHARS"

DEFAULT_PROVIDER = "openai_compatible"
DEFAULT_BASE_URL = "https://api.freemodel.dev"
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_ENABLE_CHAT_FALLBACK = False
DEFAULT_MAX_INPUT_CHARS = 8000


def default_llm_metadata(*, enabled: bool = False) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "used": False,
        "provider": DEFAULT_PROVIDER,
        "base_url": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "chat_fallback_enabled": DEFAULT_ENABLE_CHAT_FALLBACK,
        "max_input_chars": DEFAULT_MAX_INPUT_CHARS,
        "calls": 0,
        "errors": [],
    }


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return default


def _parse_max_input_chars(value: str | None) -> tuple[int, tuple[str, ...]]:
    if value is None or not value.strip():
        return DEFAULT_MAX_INPUT_CHARS, ()
    try:
        parsed = int(value)
    except ValueError:
        return (
            DEFAULT_MAX_INPUT_CHARS,
            (
                f"{MAX_INPUT_CHARS_ENV}={value!r} 不是合法整数，已使用默认值 "
                f"{DEFAULT_MAX_INPUT_CHARS}。",
            ),
        )
    if parsed <= 0:
        return (
            DEFAULT_MAX_INPUT_CHARS,
            (
                f"{MAX_INPUT_CHARS_ENV}={value!r} 必须大于 0，已使用默认值 "
                f"{DEFAULT_MAX_INPUT_CHARS}。",
            ),
        )
    return parsed, ()


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    api_key: str | None
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    enable_chat_fallback: bool = DEFAULT_ENABLE_CHAT_FALLBACK
    max_input_chars: int = DEFAULT_MAX_INPUT_CHARS
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> OpenAICompatibleConfig:
        env = environ or os.environ
        api_key = env.get(API_KEY_ENV) or None
        base_url = env.get(BASE_URL_ENV) or DEFAULT_BASE_URL
        model = env.get(MODEL_ENV) or DEFAULT_MODEL
        enable_chat_fallback = _parse_bool(env.get(ENABLE_CHAT_FALLBACK_ENV))
        max_input_chars, warnings = _parse_max_input_chars(env.get(MAX_INPUT_CHARS_ENV))
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            enable_chat_fallback=enable_chat_fallback,
            max_input_chars=max_input_chars,
            warnings=warnings,
        )

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def to_metadata(self, *, enabled: bool) -> dict[str, Any]:
        metadata = default_llm_metadata(enabled=enabled)
        metadata["base_url"] = self.base_url
        metadata["model"] = self.model
        metadata["chat_fallback_enabled"] = self.enable_chat_fallback
        metadata["max_input_chars"] = self.max_input_chars
        return metadata
