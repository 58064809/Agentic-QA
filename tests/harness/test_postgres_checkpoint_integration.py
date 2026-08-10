from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from harness.infrastructure.local_config import FilesystemLocalConfigLoader
from harness.infrastructure.persistence.postgres_checkpoint import (
    CheckpointPostgresConfig,
    postgres_checkpointer,
)


class CounterState(TypedDict):
    value: int


def _postgres_config() -> CheckpointPostgresConfig:
    value = FilesystemLocalConfigLoader(Path.cwd()).load_required().postgres
    if value.password == "local-validation-only":
        pytest.skip("postgres.password is still the local placeholder")
    return CheckpointPostgresConfig(
        host=value.host,
        port=value.port,
        database=value.database,
        user=value.user,
        password=value.password,
        connect_timeout_seconds=value.connect_timeout_seconds,
    )


def _interrupt_graph(checkpointer):
    builder = StateGraph(CounterState)

    def wait_for_value(state: CounterState) -> CounterState:
        increment = int(interrupt({"current": state["value"]}))
        return {"value": state["value"] + increment}

    builder.add_node("wait_for_value", wait_for_value)
    builder.add_edge(START, "wait_for_value")
    builder.add_edge("wait_for_value", END)
    return builder.compile(checkpointer=checkpointer)


@pytest.mark.postgres
def test_checkpoint_setup_interrupt_and_cross_connection_resume() -> None:
    postgres = _postgres_config()
    config = {"configurable": {"thread_id": "workspace-a:run-cross-connection"}}

    with postgres_checkpointer(postgres) as checkpointer:
        first = _interrupt_graph(checkpointer).invoke({"value": 2}, config)
        assert first["__interrupt__"]

    with postgres_checkpointer(postgres) as checkpointer:
        resumed = _interrupt_graph(checkpointer).invoke(Command(resume=3), config)

    assert resumed["value"] == 5


@pytest.mark.postgres
def test_concurrent_workspace_qualified_checkpoint_threads() -> None:
    postgres = _postgres_config()

    def execute(index: int) -> int:
        thread_id = f"workspace-{index % 2}:run-{index}"
        config = {"configurable": {"thread_id": thread_id}}
        with postgres_checkpointer(postgres) as checkpointer:
            builder = StateGraph(CounterState)
            builder.add_node("increment", lambda state: {"value": state["value"] + 1})
            builder.add_edge(START, "increment")
            builder.add_edge("increment", END)
            result = builder.compile(checkpointer=checkpointer).invoke({"value": index}, config)
            return result["value"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(execute, range(8)))

    assert results == [index + 1 for index in range(8)]
