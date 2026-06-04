from __future__ import annotations

import argparse
from pathlib import Path

from create_prd_workspace import generate_markdown_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="生成 Markdown QA 报告草稿到 report/qa-review.md"
    )
    parser.add_argument("workspace", help="PRD 工作区路径")
    args = parser.parse_args()

    report = generate_markdown_report(Path(args.workspace))
    print(f"已生成报告草稿: {report.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
