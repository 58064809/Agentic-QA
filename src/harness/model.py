from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ModelGateway(Protocol):
    def structured(
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        tools: list[dict[str, Any]] | None = None,
    ) -> T: ...


@dataclass(frozen=True)
class ModelConfig:
    model: str
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None

    @classmethod
    def from_env(cls) -> ModelConfig | None:
        model = os.getenv("AGENTIC_QA_MODEL", "").strip()
        if not model:
            return None
        return cls(
            model=model,
            api_key_env=os.getenv("AGENTIC_QA_MODEL_API_KEY_ENV", "OPENAI_API_KEY").strip(),
            base_url=os.getenv("AGENTIC_QA_MODEL_BASE_URL") or None,
        )


class OpenAICompatibleModelGateway:
    """One globally configured structured-output model gateway."""

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
        self._client = OpenAI(api_key=api_key, base_url=config.base_url)
        self.last_usage: dict[str, int] = {}

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        tools: list[dict[str, Any]] | None = None,
    ) -> T:
        tool_context = ""
        if tools:
            tool_context = (
                "\n可用工具 manifest（需要调用时在 tool_requests 中返回请求）：\n"
                + json.dumps(tools, ensure_ascii=False)
            )
        try:
            response = self._client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": system + tool_context},
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "strict": True,
                        "schema": response_model.model_json_schema(),
                    },
                },
            )
            usage = response.usage
            if usage is not None:
                current = {
                    "input_tokens": int(usage.prompt_tokens),
                    "output_tokens": int(usage.completion_tokens),
                    "total_tokens": int(usage.total_tokens),
                }
                self.last_usage = {
                    key: self.last_usage.get(key, 0) + value for key, value in current.items()
                }
            content = response.choices[0].message.content
            if not content:
                raise ValueError("model returned empty structured output")
            return response_model.model_validate_json(content)
        except Exception as exc:
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
            raise RuntimeError(
                f"model_gateway_error:{type(exc).__name__}:{str(exc)[:300]}"
            ) from exc


class CallableModelGateway:
    """Recorded/fake gateway used by deterministic tests and offline evals."""

    def __init__(self, callback: Callable[..., BaseModel | dict[str, Any] | str]):
        self._callback = callback

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        tools: list[dict[str, Any]] | None = None,
    ) -> T:
        try:
            result = self._callback(
                system=system,
                prompt=prompt,
                response_model=response_model,
                tools=tools or [],
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


def model_gateway_from_env() -> ModelGateway | None:
    config = ModelConfig.from_env()
    return OpenAICompatibleModelGateway(config) if config else None
