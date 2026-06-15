from __future__ import annotations

import argparse
from pathlib import Path

from create_prd_workspace import validate_workspace


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 Agentic-QA 需求工作区")
    parser.add_argument("workspace", help="需求工作区路径，例如 prd/demo-requirement")
    args = parser.parse_args()

    result = validate_workspace(Path(args.workspace))
    if result.ok:
        print(f"OK: {result.workspace.as_posix()}")
        return 0

    print(f"INVALID: {result.workspace.as_posix()}")
    for error in result.errors:
        print(f"- {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
