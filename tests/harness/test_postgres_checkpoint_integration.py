from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from harness.infrastructure.persistence.postgres_checkpoint import postgres_checkpointer


class CounterState(TypedDict):
    value: int


def _require_postgres() -> None:
    if not os.getenv("PG_LOCAL_PASSWORD"):
        pytest.skip("PG_LOCAL_PASSWORD is not configured")


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
    _require_postgres()
    config = {"configurable": {"thread_id": "workspace-a:run-cross-connection"}}

    with postgres_checkpointer() as checkpointer:
        first = _interrupt_graph(checkpointer).invoke({"value": 2}, config)
        assert first["__interrupt__"]

    with postgres_checkpointer() as checkpointer:
        resumed = _interrupt_graph(checkpointer).invoke(Command(resume=3), config)

    assert resumed["value"] == 5


@pytest.mark.postgres
def test_concurrent_workspace_qualified_checkpoint_threads() -> None:
    _require_postgres()

    def execute(index: int) -> int:
        thread_id = f"workspace-{index % 2}:run-{index}"
        config = {"configurable": {"thread_id": thread_id}}
        with postgres_checkpointer() as checkpointer:
            builder = StateGraph(CounterState)
            builder.add_node("increment", lambda state: {"value": state["value"] + 1})
            builder.add_edge(START, "increment")
            builder.add_edge("increment", END)
            result = builder.compile(checkpointer=checkpointer).invoke({"value": index}, config)
            return result["value"]

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(execute, range(8)))

    assert results == [index + 1 for index in range(8)]
