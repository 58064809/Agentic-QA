from __future__ import annotations

import re


_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization headers / bearer tokens
    (re.compile(r"(Authorization:\s*)(Bearer\s+)[^\s]+", flags=re.IGNORECASE), r"\1\2***"),
    (re.compile(r"(\"Authorization\"\s*:\s*\")([^\"\\]+)(\")", flags=re.IGNORECASE), r"\1***\3"),
    # Generic access tokens in key/value
    (re.compile(r"((?:token|access_token|accesstoken)\s*[:=]\s*)[^\s\"']+", flags=re.IGNORECASE), r"\1***"),
    # Postgres DSN credentials
    (re.compile(r"(postgres(?:ql)?://)([^:@/\s]+):([^@/\s]+)@", flags=re.IGNORECASE), r"\1***:***@"),
]


def redact_text(text: str) -> str:
    if not text:
        return text
    redacted = text
    for pattern, replacement in _PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted

