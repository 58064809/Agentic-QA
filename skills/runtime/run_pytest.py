from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def run_pytest(target: str = '', marker: str = '', keyword: str = '') -> dict[str, Any]:
    """最小 pytest 执行骨架。

    当前版本只负责组装命令并执行，后续再增强结果解析。
    """
    cmd = ['pytest']
    if target:
        cmd.append(target)
    if marker:
        cmd.extend(['-m', marker])
    if keyword:
        cmd.extend(['-k', keyword])

    result = subprocess.run(cmd, capture_output=True, text=True)

    return {
        'task': 'test_execution',
        'command': ' '.join(cmd),
        'exit_code': result.returncode,
        'stdout': result.stdout,
        'stderr': result.stderr,
    }
