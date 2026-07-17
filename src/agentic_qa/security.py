from __future__ import annotations

import re
from typing import Any

SECRET_KEY = re.compile(r"(authorization|cookie|token|secret|password|api[_-]?key)", re.I)
BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")


def sanitize_untrusted(value: Any, *, max_chars: int = 100_000) -> Any:
    """Redact common secrets and bound data returned by agents or external tools."""
    if isinstance(value, dict):
        return {
            str(key): (
                "<redacted>"
                if SECRET_KEY.search(str(key))
                else sanitize_untrusted(item, max_chars=max_chars)
            )
            for key, item in list(value.items())[:500]
        }
    if isinstance(value, list):
        return [sanitize_untrusted(item, max_chars=max_chars) for item in value[:500]]
    if isinstance(value, str):
        return BEARER.sub(r"\1 <redacted>", value)[:max_chars]
    return value
