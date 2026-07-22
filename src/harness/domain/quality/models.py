from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class QualityContext:
    workspace_id: str
    run_id: str
    artifact: str
    source_corpus: str = ""


@dataclass(frozen=True)
class QualityIssue:
    policy: str
    version: str
    code: str
    message: str


@dataclass(frozen=True)
class PolicyResult:
    content: str
    issues: tuple[QualityIssue, ...] = ()
    actions: tuple[str, ...] = ()


class QualityPolicy(Protocol):
    name: str
    version: str

    def evaluate(self, context: QualityContext, content: str) -> PolicyResult: ...


@dataclass
class QualityPolicyRegistry:
    policies: dict[str, QualityPolicy] = field(default_factory=dict)

    def register(self, policy: QualityPolicy) -> None:
        if policy.name in self.policies:
            raise ValueError(f"duplicate quality policy: {policy.name}")
        self.policies[policy.name] = policy

    def require(self, names: list[str]) -> tuple[QualityPolicy, ...]:
        unknown = sorted(set(names) - set(self.policies))
        if unknown:
            raise ValueError(f"unknown quality policies: {', '.join(unknown)}")
        return tuple(self.policies[name] for name in names)
