from __future__ import annotations

import pytest

from harness.budget import Budget, BudgetExceeded, BudgetLimits
from harness.contracts import BudgetUsage


def test_elapsed_runtime_accumulates_across_restored_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter((100.0, 105.0))
    monkeypatch.setattr("harness.domain.budget.monotonic", lambda: next(ticks))

    budget = Budget(usage=BudgetUsage(model_calls=2, elapsed_seconds=120.0))

    snapshot = budget.snapshot()
    assert snapshot.model_calls == 2
    assert snapshot.elapsed_seconds == 125.0


def test_restored_elapsed_runtime_cannot_bypass_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter((200.0, 202.0))
    monkeypatch.setattr("harness.domain.budget.monotonic", lambda: next(ticks))
    budget = Budget(
        limits=BudgetLimits(max_runtime_seconds=10),
        usage=BudgetUsage(elapsed_seconds=9.0),
    )

    with pytest.raises(BudgetExceeded, match="runtime budget exceeded"):
        budget.consume_model()

    assert budget.usage.model_calls == 0
    assert budget.usage.elapsed_seconds == 11.0


def test_concurrent_agent_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_concurrent_agents"):
        BudgetLimits(max_concurrent_agents=0)
