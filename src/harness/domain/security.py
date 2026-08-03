from __future__ import annotations

import re
from typing import Any

SECRET_KEY = re.compile(r"(authorization|cookie|token|secret|password|api[_-]?key)", re.I)
ENV_REFERENCE = re.compile(r"^\$\{[A-Z_][A-Z0-9_]*\}$")
RUNTIME_VARIABLE_REFERENCE = re.compile(r"^\$\{\{[A-Za-z_][A-Za-z0-9_]*\}\}$")
HTTP_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
TRANSPORT_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection"})
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


def _is_safe_secret_reference(value: Any, *, allow_runtime_variables: bool) -> bool:
    return isinstance(value, str) and (
        bool(ENV_REFERENCE.fullmatch(value))
        or (allow_runtime_variables and bool(RUNTIME_VARIABLE_REFERENCE.fullmatch(value)))
    )


def validate_api_data_safety(
    value: Any,
    *,
    label: str,
    allow_runtime_variables: bool,
    path: tuple[str, ...] = (),
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            current = (*path, str(key))
            if SECRET_KEY.search(str(key)) and not _is_safe_secret_reference(
                item, allow_runtime_variables=allow_runtime_variables
            ):
                raise ValueError(
                    f"{label} sensitive values must use an environment or runtime variable "
                    f"reference: {'.'.join(current)}"
                )
            validate_api_data_safety(
                item,
                label=label,
                allow_runtime_variables=allow_runtime_variables,
                path=current,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            validate_api_data_safety(
                item,
                label=label,
                allow_runtime_variables=allow_runtime_variables,
                path=(*path, str(index)),
            )
    elif isinstance(value, str) and contains_likely_secret(value):
        if not _is_safe_secret_reference(value, allow_runtime_variables=allow_runtime_variables):
            raise ValueError(f"{label} contains a likely inline secret: {'.'.join(path)}")


def validate_api_request_safety(
    *,
    path: str | None,
    headers: dict[str, Any],
    query: Any,
    body: Any,
    label: str,
    allow_runtime_variables: bool,
) -> None:
    validate_api_request_transport(path=path, headers=headers, label=label)
    validate_api_data_safety(
        headers,
        label=label,
        allow_runtime_variables=allow_runtime_variables,
        path=("headers",),
    )
    validate_api_data_safety(
        query,
        label=label,
        allow_runtime_variables=allow_runtime_variables,
        path=("query",),
    )
    validate_api_data_safety(
        body,
        label=label,
        allow_runtime_variables=allow_runtime_variables,
        path=("body",),
    )


def validate_api_request_transport(
    *,
    path: str | None,
    headers: dict[str, Any],
    label: str,
) -> None:
    if path is not None and (
        not path.startswith("/")
        or path.startswith("//")
        or "?" in path
        or "#" in path
        or "\r" in path
        or "\n" in path
    ):
        raise ValueError(f"{label} path must be relative, query-free, and start with '/'")
    invalid_headers = sorted(
        name
        for name, item in headers.items()
        if name.casefold() in TRANSPORT_HEADERS
        or not HTTP_HEADER_NAME.fullmatch(name)
        or not isinstance(item, str)
        or "\r" in item
        or "\n" in item
    )
    if invalid_headers:
        raise ValueError(
            f"{label} contains invalid or transport-controlled headers: "
            + ", ".join(invalid_headers)
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
