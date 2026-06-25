"""Agentic-QA CLI 入口。

用法:
    agentic-qa "你的自然语言命令"

代码已拆分至 ``runtime/cli/`` 子包。此文件仅保留转发入口。
"""

from __future__ import annotations

import sys

from runtime.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
