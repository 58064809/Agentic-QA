from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# ── 环境变量（DeepSeek） ─────────────────────────────────────────
API_KEY_ENV = "DEEPSEEK_API_KEY"
BASE_URL_ENV = "DEEPSEEK_BASE_URL"
MODEL_ENV = "DEEPSEEK_MODEL"
ENABLE_CHAT_FALLBACK_ENV = "DEEPSEEK_ENABLE_CHAT_FALLBACK"
MAX_INPUT_CHARS_ENV = "DEEPSEEK_MAX_INPUT_CHARS"

# ── Anthropic / Claude 兼容端 ────────────────────────────────────
CLAUDE_API_KEY_ENV = "CLAUDE_API_KEY"
CLAUDE_BASE_URL_ENV = "CLAUDE_BASE_URL"
CLAUDE_MODEL_ENV = "CLAUDE_MODEL"

DEFAULT_PROVIDER = "deepseek"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_CLAUDE_BASE_URL = "https://api.deepseek.com/anthropic"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_ENABLE_CHAT_FALLBACK = True  # DeepSeek 使用 chat completions
DEFAULT_MAX_INPUT_CHARS = 32000


def default_llm_metadata(*, enabled: bool = False) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "used": False,
        "provider": DEFAULT_PROVIDER,
        "credential_env": API_KEY_ENV,
        "base_url": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "chat_fallback_enabled": DEFAULT_ENABLE_CHAT_FALLBACK,
        "max_input_chars": DEFAULT_MAX_INPUT_CHARS,
        "calls": 0,
        "errors": [],
    }


def _config_value(config: Any, key: str, default: Any) -> Any:
    if config is None:
        return default
    if isinstance(config, Mapping):
        return config.get(key, default)
    return getattr(config, key, default)


def _config_bool(config: Any, key: str, default: bool) -> bool:
    value = _config_value(config, key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return _parse_bool(value, default=default)
    return default


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
    api_key_env: str = API_KEY_ENV

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> OpenAICompatibleConfig:
        env = environ or os.environ

        api_key = env.get(API_KEY_ENV) or None
        base_url = env.get(BASE_URL_ENV) or DEFAULT_BASE_URL
        model = env.get(MODEL_ENV) or DEFAULT_MODEL
        enable_chat_fallback = _parse_bool(env.get(ENABLE_CHAT_FALLBACK_ENV), default=DEFAULT_ENABLE_CHAT_FALLBACK)
        max_input_chars, warnings = _parse_max_input_chars(env.get(MAX_INPUT_CHARS_ENV))
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            enable_chat_fallback=enable_chat_fallback,
            max_input_chars=max_input_chars,
            warnings=warnings,
            api_key_env=API_KEY_ENV,
        )

    @classmethod
    def from_app_config(
        cls,
        config: Any,
        environ: Mapping[str, str] | None = None,
    ) -> OpenAICompatibleConfig:
        """从统一配置合并环境变量生成 LLM 调用配置。

        YAML 只保存 provider/model/base_url 等非密钥信息；密钥始终从环境变量读取。
        环境变量优先于 YAML，便于本地临时覆盖。
        """
        env = environ or os.environ
        api_key_env = str(_config_value(config, "api_key_env", API_KEY_ENV))
        base_url_env = str(_config_value(config, "base_url_env", BASE_URL_ENV))
        model_env = str(_config_value(config, "model_env", MODEL_ENV))

        api_key = env.get(api_key_env) or None
        base_url = env.get(base_url_env) or str(
            _config_value(config, "base_url", DEFAULT_BASE_URL)
        )
        model = env.get(model_env) or str(_config_value(config, "model", DEFAULT_MODEL))
        enable_chat_fallback = _parse_bool(
            env.get(ENABLE_CHAT_FALLBACK_ENV),
            default=_config_bool(
                config,
                "enable_chat_fallback",
                DEFAULT_ENABLE_CHAT_FALLBACK,
            ),
        )
        configured_max = _config_value(
            config,
            "max_input_chars",
            DEFAULT_MAX_INPUT_CHARS,
        )
        max_input_chars, warnings = _parse_max_input_chars(
            env.get(MAX_INPUT_CHARS_ENV) or str(configured_max)
        )
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            enable_chat_fallback=enable_chat_fallback,
            max_input_chars=max_input_chars,
            warnings=warnings,
            api_key_env=api_key_env,
        )

    @classmethod
    def from_metadata(
        cls,
        metadata: Mapping[str, Any],
        environ: Mapping[str, str] | None = None,
    ) -> OpenAICompatibleConfig:
        env = environ or os.environ
        api_key_env = str(
            metadata.get("credential_env")
            or metadata.get("api_key_env")
            or API_KEY_ENV
        )
        max_input_chars, warnings = _parse_max_input_chars(
            str(metadata.get("max_input_chars") or DEFAULT_MAX_INPUT_CHARS)
        )
        return cls(
            api_key=env.get(api_key_env) or None,
            base_url=str(metadata.get("base_url") or DEFAULT_BASE_URL),
            model=str(metadata.get("model") or DEFAULT_MODEL),
            enable_chat_fallback=_parse_bool(
                str(metadata.get("chat_fallback_enabled", "")),
                default=DEFAULT_ENABLE_CHAT_FALLBACK,
            ),
            max_input_chars=max_input_chars,
            warnings=warnings,
            api_key_env=api_key_env,
        )

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def to_metadata(self, *, enabled: bool) -> dict[str, Any]:
        metadata = default_llm_metadata(enabled=enabled)
        metadata["credential_env"] = self.api_key_env
        metadata["base_url"] = self.base_url
        metadata["model"] = self.model
        metadata["chat_fallback_enabled"] = self.enable_chat_fallback
        metadata["max_input_chars"] = self.max_input_chars
        return metadata
