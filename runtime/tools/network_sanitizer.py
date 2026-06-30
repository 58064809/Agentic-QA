from __future__ import annotations

import re
from typing import Any

SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-token",
    "x-access-token",
}
SENSITIVE_FIELD_NAMES = {
    "token",
    "access_token",
    "refresh_token",
    "session",
    "jsessionid",
    "cookie",
    "authorization",
    "password",
    "secret",
}
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
BANK_CARD_RE = re.compile(r"(?<!\d)\d{16,19}(?!\d)")


def sanitize_headers(headers: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in (headers or {}).items():
        if str(key).lower() in SENSITIVE_HEADER_NAMES:
            result[str(key)] = "<REDACTED>"
        else:
            result[str(key)] = sanitize_value(value)
    return result


def sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, raw in value.items():
            if str(key).lower() in SENSITIVE_FIELD_NAMES:
                sanitized[str(key)] = "<REDACTED>"
            else:
                sanitized[str(key)] = sanitize_json(raw)
        return sanitized
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    return sanitize_value(value)


def sanitize_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    value = PHONE_RE.sub(lambda match: match.group(0)[:3] + "****" + match.group(0)[-4:], value)
    value = ID_CARD_RE.sub("<REDACTED_ID_CARD>", value)
    value = BANK_CARD_RE.sub("<REDACTED_BANK_CARD>", value)
    return value


def schema_summary(value: Any) -> Any:
    value = sanitize_json(value)
    if isinstance(value, dict):
        return {str(key): schema_summary(raw) for key, raw in value.items()}
    if isinstance(value, list):
        if not value:
            return []
        return [schema_summary(value[0])]
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if value is None:
        return "null"
    return "string"
