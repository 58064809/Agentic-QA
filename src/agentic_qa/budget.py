from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic

from agentic_qa.contracts import BudgetUsage


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class BudgetLimits:
    max_model_calls: int = 24
    max_tool_calls: int = 50
    max_replans: int = 3
    max_concurrent_agents: int = 3
    max_runtime_seconds: int = 30 * 60


class Budget:
    def __init__(
        self, limits: BudgetLimits | None = None, usage: BudgetUsage | None = None
    ) -> None:
        self.limits = limits or BudgetLimits()
        self.usage = usage or BudgetUsage()
        self._started = monotonic()
        self._lock = Lock()

    def consume_model(self) -> None:
        with self._lock:
            self._check_time()
            if self.usage.model_calls >= self.limits.max_model_calls:
                raise BudgetExceeded("model call budget exceeded")
            self.usage.model_calls += 1

    def consume_tool(self) -> None:
        with self._lock:
            self._check_time()
            if self.usage.tool_calls >= self.limits.max_tool_calls:
                raise BudgetExceeded("tool call budget exceeded")
            self.usage.tool_calls += 1

    def consume_replan(self) -> None:
        with self._lock:
            self._check_time()
            if self.usage.replans >= self.limits.max_replans:
                raise BudgetExceeded("replan budget exceeded")
            self.usage.replans += 1

    def _check_time(self) -> None:
        elapsed = monotonic() - self._started
        self.usage.elapsed_seconds = elapsed
        if elapsed > self.limits.max_runtime_seconds:
            raise BudgetExceeded("runtime budget exceeded")

    def snapshot(self) -> BudgetUsage:
        with self._lock:
            self.usage.elapsed_seconds = monotonic() - self._started
            return self.usage.model_copy(deep=True)
