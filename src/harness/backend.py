"""Internal LangGraph adapter.

LangGraph types intentionally do not cross the public Harness contract. The adapter
creates dynamic dispatch messages and supervisor return commands; durable snapshots
remain domain-owned JSON so the backend can be replaced.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Command, Send

from harness.contracts import PlanTask


def dispatch(tasks: list[PlanTask]) -> list[Send]:
    return [
        Send(
            "expert_agent",
            {
                "task_id": task.id,
                "agent": task.agent,
                "objective": task.objective,
            },
        )
        for task in tasks
    ]


def return_to_supervisor(task_id: str, accepted: bool) -> Command[Any]:
    return Command(
        goto="qa_supervisor",
        update={"task_results": [{"task_id": task_id, "accepted": accepted}]},
    )
