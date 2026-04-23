from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


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
            text=True,
            encoding="utf-8",
            errors="replace",
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
            "stdout": stdout if isinstance(stdout, str) else stdout.decode(encoding="utf-8", errors="replace"),
            "stderr": stderr if isinstance(stderr, str) else stderr.decode(encoding="utf-8", errors="replace"),
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
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
    }
