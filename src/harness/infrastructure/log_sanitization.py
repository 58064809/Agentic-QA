from __future__ import annotations

import re

ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|cookie|password|passwd|secret|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|token)\b(\s*[:=]\s*)"
    r"(?:bearer\s+)?[\"']?([^\s,;\"']+)[\"']?"
)
BEARER = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?!\w)")
PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
CN_ID = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")
BANK_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)")


def sanitize_log_text(value: str, *, preserve: set[str] | None = None) -> tuple[str, int]:
    protected: dict[str, str] = {}
    text = value
    for index, item in enumerate(sorted(preserve or set(), key=len, reverse=True)):
        if not item:
            continue
        placeholder = f"<AQA-CORRELATION-{index}>"
        if item in text:
            protected[placeholder] = item
            text = text.replace(item, placeholder)
    count = 0

    def assignment(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}{match.group(2)}<redacted>"

    text = ASSIGNMENT.sub(assignment, text)
    for pattern, replacement in (
        (BEARER, "<redacted-auth>"),
        (JWT, "<redacted-jwt>"),
        (EMAIL, "<redacted-email>"),
        (PHONE, "<redacted-phone>"),
        (CN_ID, "<redacted-id>"),
        (BANK_CARD, "<redacted-card>"),
    ):
        text, replacements = pattern.subn(replacement, text)
        count += replacements
    for placeholder, item in protected.items():
        text = text.replace(placeholder, item)
    return text, count
