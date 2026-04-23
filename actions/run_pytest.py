from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def run_pytest(
    target: str = "",
    marker: str = "",
    keyword: str = "",
    workspace_root: str = "",
) -> dict[str, Any]:
    cmd = ["pytest"]
    if target:
        cmd.append(target)
    if marker:
        cmd.extend(["-m", marker])
    if keyword:
        cmd.extend(["-k", keyword])

    cwd = Path(workspace_root) if workspace_root else ROOT
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )

    return {
        "task": "test_execution",
        "command": " ".join(cmd),
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
