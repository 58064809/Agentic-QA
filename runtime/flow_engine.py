from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FlowRun:
    name: str
    configured_steps: list[str]
    executed_steps: list[dict[str, Any]] = field(default_factory=list)

    def record(self, step: str, status: str = "ok", **details: Any) -> None:
        self.executed_steps.append(
            {
                "step": step,
                "status": status,
                "details": details,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "configured_steps": self.configured_steps,
            "executed_steps": self.executed_steps,
        }


def load_flow(flow_name: str) -> dict:
    flow_file = ROOT / "flows" / f"{flow_name}.yaml"
    return yaml.safe_load(flow_file.read_text(encoding="utf-8"))


def start_flow(flow: dict[str, Any]) -> FlowRun:
    return FlowRun(
        name=flow.get("name", "unknown"),
        configured_steps=list(flow.get("steps", [])),
    )
