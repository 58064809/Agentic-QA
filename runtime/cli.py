from __future__ import annotations

import argparse
from pathlib import Path

from runtime.graph.app import (
    run_mvp_analysis_and_testcases_workflow,
    run_mvp_testcase_generation_workflow,
    run_requirement_analysis_workflow,
    run_testcase_generation_workflow,
)


def add_common_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("user_input", help="用户自然语言命令")
    parser.add_argument("--prd", required=True, help="PRD 工作区路径")
    parser.add_argument(
        "--approve-write",
        action="store_true",
        help="显式允许写入草稿；默认 dry-run 不写入业务产物。",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="显式启用本地环境变量配置的 OpenAI-compatible LLM；默认关闭。",
    )
    parser.add_argument(
        "--record-run",
        dest="record_run",
        action="store_true",
        default=True,
        help="生成本地运行记录；默认开启。",
    )
    parser.add_argument(
        "--no-record-run",
        dest="record_run",
        action="store_false",
        help="不生成本地运行记录。",
    )


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
    run_parser.add_argument(
        "--record-run",
        dest="record_run",
        action="store_true",
        default=True,
        help="生成本地运行记录；默认开启",
    )
    run_parser.add_argument(
        "--no-record-run",
        dest="record_run",
        action="store_false",
        help="不生成本地运行记录",
    )

    analyze_parser = subparsers.add_parser("analyze", help="生成需求分析草稿")
    add_common_runtime_arguments(analyze_parser)

    testcase_parser = subparsers.add_parser(
        "generate-testcases",
        help="生成测试用例草稿",
    )
    add_common_runtime_arguments(testcase_parser)

    mvp_parser = subparsers.add_parser(
        "mvp",
        help="连续生成需求分析草稿和测试用例草稿",
    )
    add_common_runtime_arguments(mvp_parser)
    return parser


def print_summary(result) -> None:
    print("Runtime 执行摘要")
    print(f"- 编排方式: {result.orchestration}")
    print(f"- 模式: {'approve-write' if result.approve_write else 'dry-run'}")
    print(f"- 任务类型: {result.task_type or 'legacy_testcase_generation'}")
    print(f"- 意图: {result.intent or '未识别'}")
    print(f"- PRD: {result.prd_path}")
    print(f"- 目标输出: {result.output_path or '未生成'}")
    if result.output_paths:
        print("- 产物路径:")
        for name, output_path in result.output_paths.items():
            print(f"  - {name}: {output_path}")
    print(f"- 是否写入文件: {'是' if result.wrote_file else '否'}")
    if result.llm:
        print(
            "- LLM: "
            f"enabled={result.llm.get('enabled')}, "
            f"used={result.llm.get('used')}, "
            f"model={result.llm.get('model')}, "
            f"calls={result.llm.get('calls')}"
        )
    if result.requirement_normalization:
        normalization = result.requirement_normalization
        print(
            "- 需求文档归一化: "
            f"performed={normalization.get('performed')}, "
            f"source={normalization.get('source_path') or '无'}, "
            f"output={normalization.get('output_path') or '无'}, "
            f"reason={normalization.get('skipped_reason') or '无'}"
        )
    print(f"- Run ID: {result.run_id or '未生成'}")
    if result.run_summary_json and result.run_summary_md:
        print(f"- 运行记录 JSON: {result.run_summary_json}")
        print(f"- 运行记录 Markdown: {result.run_summary_md}")
    else:
        print("- 运行记录: 未生成（--no-record-run）")
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
            record_run=args.record_run,
        )
        print_summary(result)
        return 0 if result.success else 1

    if args.command == "analyze":
        result = run_requirement_analysis_workflow(
            user_input=args.user_input,
            prd_path=Path(args.prd),
            approve_write=args.approve_write,
            record_run=args.record_run,
            use_llm=args.use_llm,
        )
        print_summary(result)
        return 0 if result.success else 1

    if args.command == "generate-testcases":
        result = run_mvp_testcase_generation_workflow(
            user_input=args.user_input,
            prd_path=Path(args.prd),
            approve_write=args.approve_write,
            record_run=args.record_run,
            use_llm=args.use_llm,
        )
        print_summary(result)
        return 0 if result.success else 1

    if args.command == "mvp":
        result = run_mvp_analysis_and_testcases_workflow(
            user_input=args.user_input,
            prd_path=Path(args.prd),
            approve_write=args.approve_write,
            record_run=args.record_run,
            use_llm=args.use_llm,
        )
        print_summary(result)
        return 0 if result.success else 1

    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
