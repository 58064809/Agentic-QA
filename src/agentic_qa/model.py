from __future__ import annotations

import json
from collections.abc import Callable
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


class CallableModelGateway:
    """Single normalization point for recorded, fake, or provider-backed model calls."""

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
