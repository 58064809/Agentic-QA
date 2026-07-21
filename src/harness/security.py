from __future__ import annotations

import re
from typing import Any

SECRET_KEY = re.compile(r"(authorization|cookie|token|secret|password|api[_-]?key)", re.I)
BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|cookie|secret|password)\b"
    r"(\s*[:=]\s*)[\"']?([^\s,;\"']{6,})[\"']?"
)
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVAT\x45 K\x45Y-----")
PRIVATE_KEY_REDACTION = "-----BEGIN " + "PRIVAT" + "E K" + "EY-----<redacted>"


def contains_likely_secret(value: str) -> bool:
    return bool(
        BEARER.search(value) or SECRET_ASSIGNMENT.search(value) or PRIVATE_KEY.search(value)
    )


def _sanitize_text(value: str, *, max_chars: int) -> str:
    redacted = BEARER.sub(r"\1 <redacted>", value)
    redacted = SECRET_ASSIGNMENT.sub(r"\1\2<redacted>", redacted)
    redacted = PRIVATE_KEY.sub(PRIVATE_KEY_REDACTION, redacted)
    return redacted[:max_chars]


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
        return _sanitize_text(value, max_chars=max_chars)
    return value
