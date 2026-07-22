from __future__ import annotations

from contextlib import contextmanager

import pytest
from langgraph.checkpoint.memory import InMemorySaver


@pytest.fixture(autouse=True)
def isolated_checkpointer(monkeypatch, request):
    """Keep unit tests infrastructure-free; production has no memory fallback."""

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
    yield
