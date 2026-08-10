from __future__ import annotations

from contextlib import contextmanager

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from harness.domain.schemas.local_config import AgenticQaLocalConfig
from harness.infrastructure.local_config import FilesystemLocalConfigLoader


def _unit_test_local_config() -> AgenticQaLocalConfig:
    return AgenticQaLocalConfig.model_validate(
        {
            "model": {
                "provider": "recorded",
                "api_key_env": "DEEPSEEK_API_KEY",
                "flash_model": "recorded-flash",
                "pro_model": "recorded-pro",
                "base_url": "https://model.example.test",
            },
            "rag": {"provider": "local-lexical"},
            "postgres": {
                "host": "localhost",
                "port": 5432,
                "database": "postgres",
                "user": "postgres",
                "password": "unit-test-only",
            },
            "test_management": {"provider": "none"},
            "workspace_defaults": {},
            "api": {"services": {}},
        }
    )


@pytest.fixture(autouse=True)
def isolated_checkpointer(monkeypatch, request):
    """Keep unit tests infrastructure-free; production has no memory fallback."""

    monkeypatch.setenv("UNIT_MODEL_KEY", "unit-test-model-key")
    if request.node.get_closest_marker("postgres"):
        yield
        return

    checkpointer = InMemorySaver()

    @contextmanager
    def factory():
        yield checkpointer

    monkeypatch.setattr(
        "harness.infrastructure.persistence.postgres_checkpoint.PostgresCheckpointProvider.open",
        lambda _self: factory(),
    )
    original = FilesystemLocalConfigLoader.load_required

    def load_required(loader: FilesystemLocalConfigLoader):
        if loader.path.is_file():
            return original(loader)
        return _unit_test_local_config()

    monkeypatch.setattr(FilesystemLocalConfigLoader, "load_required", load_required)
    yield
