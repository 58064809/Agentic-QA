from __future__ import annotations

import os
import re
from typing import Protocol

from harness.domain.schemas.local_config import (
    EnvironmentSecretProviderConfig,
    LocalMappingSecretProviderConfig,
    LocalSecretProviderConfig,
)

SECRET_REFERENCE = re.compile(r"^secret://([A-Za-z0-9][A-Za-z0-9_.-]{0,199})$")


class SecretProvider(Protocol):
    def resolve(self, reference: str) -> str: ...


class LocalMappingSecretProvider:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def resolve(self, reference: str) -> str:
        value = self._values.get(reference)
        if value is None:
            raise KeyError(reference)
        getter = getattr(value, "get_secret_value", None)
        return str(getter() if getter is not None else value)


class EnvironmentSecretProvider:
    def __init__(self, variables: dict[str, str]) -> None:
        self._variables = variables

    def resolve(self, reference: str) -> str:
        environment_name = self._variables.get(reference)
        if environment_name is None:
            raise KeyError(reference)
        return os.environ.get(environment_name, "")


def build_secret_provider(config: LocalSecretProviderConfig) -> SecretProvider:
    if isinstance(config, LocalMappingSecretProviderConfig):
        return LocalMappingSecretProvider(dict(config.values))
    if isinstance(config, EnvironmentSecretProviderConfig):
        return EnvironmentSecretProvider(dict(config.variables))
    raise TypeError("unsupported secret provider")


def parse_secret_reference(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("secret-bearing configuration field must use a secret:// reference")
    match = SECRET_REFERENCE.fullmatch(value)
    if match is None:
        raise ValueError("secret-bearing configuration field must use a secret:// reference")
    return match.group(1)
