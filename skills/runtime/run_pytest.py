from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def run_pytest(target: str = '', marker: str = '', keyword: str = '') -> dict[str, Any]:
    """最小 pytest 执行骨架。

    当前版本负责组装命令，并固定在仓库根目录执行。
    这样从 runtime/ 启动 router 时，也能正确找到 tests/。
    """
    cmd = ['pytest']
    if target:
        cmd.append(target)
    if marker:
        cmd.extend(['-m', marker])
    if keyword:
        cmd.extend(['-k', keyword])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )

    return {
        'task': 'test_execution',
        'command': ' '.join(cmd),
        'cwd': str(ROOT),
        'exit_code': result.returncode,
        'stdout': result.stdout,
        'stderr': result.stderr,
    }
