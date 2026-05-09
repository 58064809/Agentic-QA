from __future__ import annotations

from datetime import UTC, datetime
from secrets import token_hex


def generate_run_id(now: datetime | None = None, random_suffix: str | None = None) -> str:
    timestamp = now or datetime.now(tz=UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    suffix = random_suffix or token_hex(3)
    return f"run-{timestamp.strftime('%Y%m%d-%H%M%S')}-{suffix}"
