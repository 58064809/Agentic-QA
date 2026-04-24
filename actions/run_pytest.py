from __future__ import annotations

import locale
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _decode_process_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value

    candidates: list[tuple[str, str]] = []
    tried: set[str] = set()
    for encoding in ["utf-8", locale.getpreferredencoding(False), "gbk", "cp936"]:
        if not encoding or encoding in tried:
            continue
        tried.add(encoding)
        try:
            candidates.append((encoding, value.decode(encoding)))
        except UnicodeDecodeError:
            continue

    if not candidates:
        return value.decode("utf-8", errors="replace")

    utf8_text = next((text for encoding, text in candidates if encoding.lower().replace("-", "") == "utf8"), "")
    if utf8_text and _contains_cjk(utf8_text) and "\ufffd" not in utf8_text:
        return utf8_text

    best_text = max(candidates, key=lambda item: _decode_score(item[1]))[1]
    return best_text


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _decode_score(text: str) -> int:
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    replacement_count = text.count("\ufffd")
    return cjk_count * 10 - replacement_count * 100


def run_pytest(
    target: str = "",
    marker: str = "",
    keyword: str = "",
    workspace_root: str = "",
    extra_args: list[str] | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    cmd = ["pytest"]
    if target:
        cmd.append(target)
    if marker:
        cmd.extend(["-m", marker])
    if keyword:
        cmd.extend(["-k", keyword])
    if extra_args:
        cmd.extend(extra_args)

    cwd = Path(workspace_root) if workspace_root else ROOT
    start_time = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            cwd=str(cwd),
            timeout=timeout_seconds,
        )
        duration_seconds = round(time.perf_counter() - start_time, 3)
    except subprocess.TimeoutExpired as exc:
        duration_seconds = round(time.perf_counter() - start_time, 3)
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        return {
            "_ok": False,
            "_error": "pytest_timeout",
            "_metadata": {"duration_seconds": duration_seconds, "timeout_seconds": timeout_seconds},
            "task": "test_execution",
            "command": " ".join(cmd),
            "command_args": cmd,
            "cwd": str(cwd),
            "exit_code": 124,
            "duration_seconds": duration_seconds,
            "timeout_seconds": timeout_seconds,
            "stdout": _decode_process_output(stdout),
            "stderr": _decode_process_output(stderr),
        }

    return {
        "_ok": result.returncode == 0,
        "_error": "" if result.returncode == 0 else "pytest_failed",
        "_metadata": {"duration_seconds": duration_seconds},
        "task": "test_execution",
        "command": " ".join(cmd),
        "command_args": cmd,
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "duration_seconds": duration_seconds,
        "timeout_seconds": timeout_seconds,
        "stdout": _decode_process_output(result.stdout),
        "stderr": _decode_process_output(result.stderr),
    }
