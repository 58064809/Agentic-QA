from __future__ import annotations

import argparse
from pathlib import Path

from create_prd_workspace import archive_requirement


def main() -> int:
    parser = argparse.ArgumentParser(description="检查审核状态并生成需求归档索引")
    parser.add_argument("workspace", help="PRD 工作区路径")
    args = parser.parse_args()

    try:
        archive = archive_requirement(Path(args.workspace))
    except RuntimeError as exc:
        print(f"归档失败: {exc}")
        return 1

    print(f"已生成归档索引: {archive.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
