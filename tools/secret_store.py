from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path


class SecretStore:
    def __init__(self, cache_file: str | Path | None = None, *, allow_plaintext_fallback: bool = False) -> None:
        self.cache_file = Path(cache_file) if cache_file else Path.home() / ".ai-assistant" / "secrets.json"
        self.allow_plaintext_fallback = allow_plaintext_fallback

    def get(self, name: str, default: str = "") -> str:
        env_value = os.getenv(name)
        if env_value:
            return env_value

        data = self._load()
        record = data.get(name)
        if not record:
            return default
        if record.get("encoding") == "dpapi":
            return _dpapi_unprotect(base64.b64decode(record["value"]))
        if record.get("encoding") == "plain" and self.allow_plaintext_fallback:
            return str(record.get("value", default))
        return default

    def set(self, name: str, value: str) -> None:
        data = self._load()
        if _dpapi_available():
            data[name] = {"encoding": "dpapi", "value": base64.b64encode(_dpapi_protect(value)).decode("ascii")}
        elif self.allow_plaintext_fallback:
            data[name] = {"encoding": "plain", "value": value}
        else:
            raise RuntimeError("Persistent secret storage requires Windows DPAPI or allow_plaintext_fallback=True")
        self._save(data)

    def delete(self, name: str) -> None:
        data = self._load()
        data.pop(name, None)
        self._save(data)

    def _load(self) -> dict[str, dict[str, str]]:
        if not self.cache_file.exists():
            return {}
        return json.loads(self.cache_file.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, dict[str, str]]) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_available() -> bool:
    return sys.platform.startswith("win")


def _dpapi_protect(value: str) -> bytes:
    data = value.encode("utf-8")
    in_buffer = ctypes.create_string_buffer(data)
    in_blob = _DataBlob(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char)))
    out_blob = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(value: bytes) -> str:
    in_buffer = ctypes.create_string_buffer(value)
    in_blob = _DataBlob(len(value), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_char)))
    out_blob = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)
