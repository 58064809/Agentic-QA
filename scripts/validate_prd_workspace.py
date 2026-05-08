from __future__ import annotations

import argparse
from pathlib import Path

from create_prd_workspace import validate_workspace


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 PRD 需求工作区结构")
    parser.add_argument("workspace", help="PRD 工作区路径")
    args = parser.parse_args()

    result = validate_workspace(Path(args.workspace))
    if result.ok:
        print(f"PRD 工作区校验通过: {result.workspace.as_posix()}")
        return 0

    print(f"PRD 工作区校验失败: {result.workspace.as_posix()}")
    for error in result.errors:
        print(f"- {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
