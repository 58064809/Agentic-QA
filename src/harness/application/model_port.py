from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel

from harness.domain.models import PlanTask, StartRunCommand

T = TypeVar("T", bound=BaseModel)
ModelTier = Literal["flash", "pro"]
ThinkingMode = Literal["enabled", "disabled"]
ReasoningEffort = Literal["high", "max"]


@dataclass(frozen=True)
class ModelRoute:
    tier: ModelTier
    thinking: ThinkingMode
    purpose: str
    reasoning_effort: ReasoningEffort | None = None

    def as_record(self, *, model: str | None = None) -> dict[str, Any]:
        record = asdict(self)
        if model is not None:
            record["model"] = model
        return record


class ModelPolicy:
    _complex_artifacts = frozenset({"execution_report", "failure_analysis", "bug_draft"})
    _pro_agents = frozenset({"risk_strategist", "test_designer", "failure_triager"})

    def for_planner(self, request: StartRunCommand) -> ModelRoute:
        if (
            set(request.expected_artifacts) & self._complex_artifacts
            or len(request.expected_artifacts) >= 4
        ):
            return ModelRoute(
                tier="pro",
                thinking="enabled",
                reasoning_effort="max",
                purpose="supervisor_complex_plan",
            )
        return ModelRoute(
            tier="flash", thinking="enabled", reasoning_effort="high", purpose="supervisor_plan"
        )

    def for_task(self, task: PlanTask) -> ModelRoute:
        if task.agent == "test_designer":
            return ModelRoute(tier="pro", thinking="disabled", purpose=f"expert:{task.agent}")
        if task.agent in self._pro_agents:
            return ModelRoute(
                tier="pro",
                thinking="enabled",
                reasoning_effort="high",
                purpose=f"expert:{task.agent}",
            )
        return ModelRoute(tier="flash", thinking="disabled", purpose=f"expert:{task.agent}")


class ModelGateway(Protocol):
    route_history: list[dict[str, Any]]

    def describe_route(self, route: ModelRoute) -> dict[str, Any]: ...

    def last_call_usage(self) -> dict[str, int]: ...

    def structured(
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        tools: list[dict[str, Any]] | None = None,
        route: ModelRoute | None = None,
    ) -> T: ...
