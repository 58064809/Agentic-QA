from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock, local
from typing import Any, TypeVar

from pydantic import BaseModel

from harness.application.model_port import ModelGateway, ModelRoute
from harness.domain.schemas.local_config import LocalModelConfig

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
    max_output_tokens: int = 32768

    @classmethod
    def from_local(cls, value: LocalModelConfig) -> ModelConfig:
        return cls(
            flash_model=value.flash_model,
            pro_model=value.pro_model,
            api_key_env=value.api_key_env,
            base_url=value.base_url,
            request_timeout_seconds=value.timeout_seconds,
            max_output_tokens=value.max_output_tokens,
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
        self._local.last_call_diagnostics = {
            "input_context_characters": len(system) + len(prompt),
        }
        started = time.perf_counter()
        selected = route or ModelRoute(
            tier="flash",
            thinking="disabled",
            purpose="unspecified",
        )
        route_record = self.describe_route(selected)
        model = str(route_record["model"])
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
                        "content": system,
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
            choice = response.choices[0]
            self._local.last_call_diagnostics = {
                **self._local.last_call_diagnostics,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "finish_reason": getattr(choice, "finish_reason", None),
                "raw_response_sha256": (
                    f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"
                    if content
                    else None
                ),
            }
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
            self._local.last_call_diagnostics = {
                **getattr(self._local, "last_call_diagnostics", {}),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "failure_stage": (
                    "structured_output_validation"
                    if isinstance(exc, ValueError)
                    else "model_request"
                ),
            }
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
            raise RuntimeError(
                f"model_gateway_error:{type(exc).__name__}:{str(exc)[:300]}"
            ) from exc

    def last_call_usage(self) -> dict[str, int]:
        return dict(getattr(self._local, "last_call_usage", {}))

    def last_call_diagnostics(self) -> dict[str, Any]:
        return dict(getattr(self._local, "last_call_diagnostics", {}))


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
        self._local.last_call_diagnostics = {
            "input_context_characters": len(system) + len(prompt),
        }
        started = time.perf_counter()
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
            validated = response_model.model_validate(result)
            raw = validated.model_dump_json()
            self._local.last_call_diagnostics = {
                **self._local.last_call_diagnostics,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "finish_reason": "recorded",
                "raw_response_sha256": (
                    f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"
                ),
            }
            return validated
        except Exception as exc:
            self._local.last_call_diagnostics = {
                **getattr(self._local, "last_call_diagnostics", {}),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "failure_stage": "structured_output_validation",
            }
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
            raise RuntimeError(
                f"model_gateway_error:{type(exc).__name__}:{str(exc)[:300]}"
            ) from exc

    def last_call_usage(self) -> dict[str, int]:
        return dict(getattr(self._local, "last_call_usage", {}))

    def last_call_diagnostics(self) -> dict[str, Any]:
        return dict(getattr(self._local, "last_call_diagnostics", {}))


def model_gateway_from_config(config: LocalModelConfig) -> ModelGateway:
    return OpenAICompatibleModelGateway(ModelConfig.from_local(config))


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
