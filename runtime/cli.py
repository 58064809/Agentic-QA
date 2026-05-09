from __future__ import annotations

import argparse
from pathlib import Path

from runtime.graph.app import run_testcase_generation_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agentic-QA Runtime 最小骨架")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="运行 Runtime dry-run 流程")
    run_parser.add_argument("user_input", help="用户自然语言命令")
    run_parser.add_argument("--prd", required=True, help="PRD 工作区路径")
    run_parser.add_argument(
        "--approve-write",
        action="store_true",
        help="显式允许写入测试用例草稿；默认 dry-run 不写入",
    )
    return parser


def print_summary(result) -> None:
    print("Runtime Skeleton 执行摘要")
    print(f"- 编排方式: {result.orchestration}")
    print(f"- 模式: {'approve-write' if result.approve_write else 'dry-run'}")
    print(f"- 意图: {result.intent or '未识别'}")
    print(f"- PRD: {result.prd_path}")
    print(f"- 目标输出: {result.output_path or '未生成'}")
    print(f"- 是否写入文件: {'是' if result.wrote_file else '否'}")
    print(f"- 人工审核状态: {result.review_status}")
    print(f"- 已执行节点: {', '.join(result.executed_nodes) if result.executed_nodes else '无'}")
    print(f"- 已加载文件数: {len(result.loaded_files)}")

    if result.warnings:
        print("警告:")
        for warning in result.warnings:
            print(f"- {warning}")

    if result.errors or result.quality_errors:
        print("错误:")
        for error in result.errors + result.quality_errors:
            print(f"- {error}")

    if not result.approve_write:
        print("说明: dry-run 不写入文件；需要写入时请显式传入 --approve-write。")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        result = run_testcase_generation_workflow(
            user_input=args.user_input,
            prd_path=Path(args.prd),
            approve_write=args.approve_write,
        )
        print_summary(result)
        return 0 if result.success else 1

    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
