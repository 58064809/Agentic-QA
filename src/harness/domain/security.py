from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlsplit

SECRET_KEY = re.compile(
    r"(authorization|cookie|token|secret|password|credential|api[_-]?key)", re.I
)
ENV_REFERENCE = re.compile(r"^\$\{[A-Z_][A-Z0-9_]*\}$")
RUNTIME_VARIABLE_REFERENCE = re.compile(r"^\$\{\{[A-Za-z_][A-Za-z0-9_]*\}\}$")
HTTP_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
TRANSPORT_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection"})
BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|cookie|secret|password)\b"
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


def validate_api_assertion_expected_safety(
    value: Any,
    *,
    label: str,
    path: tuple[str, ...] = (),
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            current = (*path, str(key))
            if SECRET_KEY.search(str(key)):
                raise ValueError(
                    f"{label} contains a sensitive expected field: {'.'.join(current)}"
                )
            validate_api_assertion_expected_safety(item, label=label, path=current)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            validate_api_assertion_expected_safety(
                item,
                label=label,
                path=(*path, str(index)),
            )
    elif isinstance(value, str) and contains_likely_secret(value):
        raise ValueError(f"{label} contains a likely sensitive expected value")


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
    if path is not None:
        _validate_api_url_path(path, label=f"{label} path")
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


def validate_api_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "API base URL must be an HTTP(S) origin/path without credentials, query, or fragment"
        )
    _api_origin(value, label="API base URL")
    _validate_api_url_path(parsed.path or "/", label="API base URL path")
    return value.rstrip("/")


def validate_api_trusted_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("trusted API origins must be HTTPS origins without paths or credentials")
    _scheme, host, port = _api_origin(value, label="trusted API origin")
    host_text = f"[{host}]" if ":" in host else host
    return f"https://{host_text}" + (f":{port}" if port != 443 else "")


def validate_api_base_url_policy(value: str, *, trusted_origins: list[str]) -> str:
    normalized = validate_api_base_url(value)
    if urlsplit(normalized).scheme.casefold() != "https":
        raise ValueError("workspace policy requires an HTTPS API base URL")
    actual_origin = _api_origin(normalized, label="API base URL")
    allowed_origins = {
        _api_origin(validate_api_trusted_origin(origin), label="trusted API origin")
        for origin in trusted_origins
    }
    if actual_origin not in allowed_origins:
        raise ValueError("API base URL origin is not trusted by workspace policy")
    return normalized


def build_api_request_url(base_url: str, request_path: str) -> str:
    normalized_base = validate_api_base_url(base_url)
    validate_api_request_transport(path=request_path, headers={}, label="resolved API request")
    final_url = normalized_base + "/" + request_path.lstrip("/")
    parsed_base = urlsplit(normalized_base)
    parsed_final = urlsplit(final_url)
    if _api_origin(final_url, label="final API URL") != _api_origin(
        normalized_base, label="API base URL"
    ):
        raise ValueError("final API URL origin differs from the configured base URL")
    expected_path = parsed_base.path.rstrip("/") + "/" + request_path.lstrip("/")
    if parsed_final.path != expected_path:
        raise ValueError("final API URL path differs from the configured base path")
    _validate_api_url_path(parsed_final.path, label="final API URL path")
    return final_url


def validate_api_response_url(response_url: Any, *, requested_url: str) -> None:
    if not isinstance(response_url, str) or not response_url.strip():
        return
    if _api_origin(response_url, label="final response URL") != _api_origin(
        requested_url, label="requested API URL"
    ):
        raise ValueError("final response URL origin differs from the requested API URL")
    response_path = urlsplit(response_url).path
    requested_path = urlsplit(requested_url).path
    _validate_api_url_path(response_path, label="final response URL path")
    if response_path != requested_path:
        raise ValueError("final response URL path differs from the requested API URL")


def _api_origin(value: str, *, label: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{label} must use an HTTP(S) origin")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{label} cannot contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} has an invalid port") from exc
    effective_port = port or (443 if parsed.scheme.casefold() == "https" else 80)
    return parsed.scheme.casefold(), parsed.hostname.casefold(), effective_port


def _validate_api_url_path(path: str, *, label: str) -> None:
    decoded = path
    for _ in range(4):
        folded = decoded.casefold()
        if "\\" in decoded or any(token in folded for token in ("%2f", "%5c", "%2e", "%3f", "%23")):
            raise ValueError(f"{label} contains an encoded or alternate path separator")
        unquoted = unquote(decoded)
        if unquoted == decoded:
            break
        decoded = unquoted
    if any(ord(character) < 32 or ord(character) == 127 for character in decoded):
        raise ValueError(f"{label} contains an encoded control character")
    segments = decoded.split("/")
    if "\\" in decoded or any(segment in {".", ".."} for segment in segments):
        raise ValueError(f"{label} contains a path traversal segment")
    if "//" in decoded:
        raise ValueError(f"{label} contains an empty path segment")


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
