from __future__ import annotations

import argparse
from pathlib import Path

from create_prd_workspace import collect_test_results


def main() -> int:
    parser = argparse.ArgumentParser(description="收集 PRD 工作区中的测试结果")
    parser.add_argument("workspace", help="PRD 工作区路径")
    args = parser.parse_args()

    summary = collect_test_results(Path(args.workspace))
    print(f"已生成测试结果汇总: {summary.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
