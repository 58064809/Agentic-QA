from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock, local
from typing import Any, TypeVar

from pydantic import BaseModel

from harness.application.model_port import ModelGateway, ModelRoute

T = TypeVar("T", bound=BaseModel)
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_FLASH_MODEL = "deepseek-v4-flash"
DEFAULT_PRO_MODEL = "deepseek-v4-pro"


@dataclass(frozen=True)
class ModelConfig:
    flash_model: str = DEFAULT_FLASH_MODEL
    pro_model: str = DEFAULT_PRO_MODEL
    api_key_env: str = "DEEPSEEK_API_KEY"
    base_url: str | None = DEFAULT_DEEPSEEK_BASE_URL
    request_timeout_seconds: float = 180.0
    max_output_tokens: int = 16384

    @classmethod
    def from_env(cls) -> ModelConfig | None:
        single_model = os.getenv("AGENTIC_QA_MODEL", "").strip()
        explicit_key_env = os.getenv("AGENTIC_QA_MODEL_API_KEY_ENV", "").strip()
        deepseek_available = bool(os.getenv("DEEPSEEK_API_KEY", "").strip())
        openai_available = bool(os.getenv("OPENAI_API_KEY", "").strip())

        if explicit_key_env:
            api_key_env = explicit_key_env
        elif deepseek_available:
            api_key_env = "DEEPSEEK_API_KEY"
        else:
            api_key_env = "OPENAI_API_KEY"

        configured = bool(
            single_model
            or os.getenv("AGENTIC_QA_MODEL_FLASH", "").strip()
            or os.getenv("AGENTIC_QA_MODEL_PRO", "").strip()
            or explicit_key_env
            or deepseek_available
        )
        if not configured:
            return None

        if api_key_env == "OPENAI_API_KEY" and not openai_available and not explicit_key_env:
            # Preserve the useful "not configured" result when no provider was selected.
            return None

        default_base_url = DEFAULT_DEEPSEEK_BASE_URL if api_key_env == "DEEPSEEK_API_KEY" else None
        return cls(
            flash_model=single_model
            or os.getenv("AGENTIC_QA_MODEL_FLASH", "").strip()
            or DEFAULT_FLASH_MODEL,
            pro_model=single_model
            or os.getenv("AGENTIC_QA_MODEL_PRO", "").strip()
            or DEFAULT_PRO_MODEL,
            api_key_env=api_key_env,
            base_url=os.getenv("AGENTIC_QA_MODEL_BASE_URL", "").strip() or default_base_url,
            request_timeout_seconds=float(
                os.getenv("AGENTIC_QA_MODEL_TIMEOUT_SECONDS", "").strip() or "180"
            ),
            max_output_tokens=int(
                os.getenv("AGENTIC_QA_MODEL_MAX_OUTPUT_TOKENS", "").strip() or "16384"
            ),
        )

    def model_for(self, route: ModelRoute) -> str:
        return self.pro_model if route.tier == "pro" else self.flash_model

    @property
    def is_deepseek(self) -> bool:
        return bool(
            self.base_url
            and self.base_url.rstrip("/").lower()
            in {DEFAULT_DEEPSEEK_BASE_URL, f"{DEFAULT_DEEPSEEK_BASE_URL}/beta"}
        )


class OpenAICompatibleModelGateway:
    """OpenAI-compatible client with centralized Flash/Pro routing."""

    def __init__(self, config: ModelConfig):
        api_key = os.getenv(config.api_key_env, "").strip()
        if not api_key:
            raise RuntimeError(
                f"model API key environment variable is not set: {config.api_key_env}"
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency gate
            raise RuntimeError("openai SDK is not installed") from exc
        self.config = config
        self._client = OpenAI(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.request_timeout_seconds,
            max_retries=0,
        )
        self._lock = Lock()
        self._local = local()
        self.last_usage: dict[str, int] = {}
        self.route_history: list[dict[str, Any]] = []

    def describe_route(self, route: ModelRoute) -> dict[str, Any]:
        return route.as_record(model=self.config.model_for(route))

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        tools: list[dict[str, Any]] | None = None,
        route: ModelRoute | None = None,
    ) -> T:
        self._local.last_call_usage = {}
        selected = route or ModelRoute(
            tier="flash",
            thinking="disabled",
            purpose="unspecified",
        )
        route_record = self.describe_route(selected)
        model = str(route_record["model"])
        tool_context = ""
        if tools:
            tool_context = (
                "\n可用工具 manifest（需要调用时在 tool_requests 中返回请求）：\n"
                + json.dumps(tools, ensure_ascii=False)
            )
        schema_context = (
            "\n必须只输出一个 JSON object，并严格满足以下 JSON Schema；不要输出 Markdown：\n"
            + json.dumps(response_model.model_json_schema(), ensure_ascii=False)
            + "\nJSON 字符串中的换行必须写成转义字符 \\n，不得写入未转义的物理换行。"
        )
        request_options: dict[str, Any] = {}
        if self.config.is_deepseek:
            request_options["extra_body"] = {"thinking": {"type": selected.thinking}}
            if selected.thinking == "enabled" and selected.reasoning_effort is not None:
                request_options["reasoning_effort"] = selected.reasoning_effort
        try:
            with self._lock:
                self.route_history.append(route_record)
            response = self._client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": system + tool_context + schema_context,
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=self.config.max_output_tokens,
                **request_options,
            )
            usage = response.usage
            if usage is not None:
                current = {
                    "input_tokens": int(usage.prompt_tokens),
                    "output_tokens": int(usage.completion_tokens),
                    "total_tokens": int(usage.total_tokens),
                }
                self._local.last_call_usage = current
                with self._lock:
                    self.last_usage = {
                        key: self.last_usage.get(key, 0) + value for key, value in current.items()
                    }
            content = response.choices[0].message.content
            if not content:
                raise ValueError("model returned empty structured output")
            try:
                return response_model.model_validate_json(content)
            except ValueError:
                repaired = _escape_json_string_control_characters(content)
                if repaired == content:
                    raise
                return response_model.model_validate_json(repaired)
        except Exception as exc:
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
            raise RuntimeError(
                f"model_gateway_error:{type(exc).__name__}:{str(exc)[:300]}"
            ) from exc

    def last_call_usage(self) -> dict[str, int]:
        return dict(getattr(self._local, "last_call_usage", {}))


class CallableModelGateway:
    """Recorded/fake gateway used by deterministic tests and offline evals."""

    def __init__(self, callback: Callable[..., BaseModel | dict[str, Any] | str]):
        self._callback = callback
        self._local = local()
        self.route_history: list[dict[str, Any]] = []

    def describe_route(self, route: ModelRoute) -> dict[str, Any]:
        return route.as_record()

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        tools: list[dict[str, Any]] | None = None,
        route: ModelRoute | None = None,
    ) -> T:
        self._local.last_call_usage = {}
        try:
            selected = route or ModelRoute(
                tier="flash",
                thinking="disabled",
                purpose="unspecified",
            )
            self.route_history.append(self.describe_route(selected))
            result = self._callback(
                system=system,
                prompt=prompt,
                response_model=response_model,
                tools=tools or [],
                route=selected,
            )
            if isinstance(result, response_model):
                return result
            if isinstance(result, BaseModel):
                result = result.model_dump(mode="json")
            if isinstance(result, str):
                result = json.loads(result)
            return response_model.model_validate(result)
        except Exception as exc:
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
            raise RuntimeError(
                f"model_gateway_error:{type(exc).__name__}:{str(exc)[:300]}"
            ) from exc

    def last_call_usage(self) -> dict[str, int]:
        return dict(getattr(self._local, "last_call_usage", {}))


def model_gateway_from_env() -> ModelGateway | None:
    config = ModelConfig.from_env()
    return OpenAICompatibleModelGateway(config) if config else None


def _escape_json_string_control_characters(payload: str) -> str:
    """Escape raw C0 controls only while inside JSON strings."""
    output: list[str] = []
    in_string = False
    escaped = False
    for character in payload:
        if not in_string:
            output.append(character)
            if character == '"':
                in_string = True
            continue
        if escaped:
            output.append(character)
            escaped = False
            continue
        if character == "\\":
            output.append(character)
            escaped = True
            continue
        if character == '"':
            output.append(character)
            in_string = False
            continue
        if ord(character) < 0x20:
            output.append(f"\\u{ord(character):04x}")
            continue
        output.append(character)
    return "".join(output)
