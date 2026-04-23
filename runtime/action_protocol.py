from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    data: dict[str, Any]
    error: str = ""
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def action_ok(
    data: dict[str, Any],
    *,
    warnings: list[str] | tuple[str, ...] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ActionResult:
    return ActionResult(
        ok=True,
        data=data,
        warnings=tuple(warnings or ()),
        metadata=metadata or {},
    )


def action_error(
    error: str,
    *,
    data: dict[str, Any] | None = None,
    warnings: list[str] | tuple[str, ...] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ActionResult:
    return ActionResult(
        ok=False,
        data=data or {},
        error=error,
        warnings=tuple(warnings or ()),
        metadata=metadata or {},
    )


def normalize_action_result(result: Any) -> ActionResult:
    if isinstance(result, ActionResult):
        return result
    if isinstance(result, dict):
        warnings = result.pop("_warnings", ())
        metadata = result.pop("_metadata", {})
        ok = result.pop("_ok", True)
        error = result.pop("_error", "")
        return ActionResult(
            ok=bool(ok),
            data=result,
            error=str(error),
            warnings=tuple(warnings or ()),
            metadata=metadata if isinstance(metadata, dict) else {},
        )
    return action_error(
        "invalid_action_result",
        data={"raw_result": result},
        warnings=("Action returned a non-dict result.",),
    )
