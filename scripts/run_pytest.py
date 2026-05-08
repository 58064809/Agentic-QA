from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="封装 pytest 执行")
    parser.add_argument("pytest_args", nargs="*", help="透传给 pytest 的参数")
    args = parser.parse_args()

    report_path = Path(".pytest_cache") / "pytest-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--json-report",
        f"--json-report-file={report_path.as_posix()}",
        *args.pytest_args,
    ]
    print("执行命令: " + " ".join(command), flush=True)
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
