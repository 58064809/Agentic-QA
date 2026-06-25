"""CLI: RAG 调试命令 (status / build / search)。"""

from __future__ import annotations

from pathlib import Path

import yaml

from runtime.config import load_app_config


def run_rag_command(args: list[str], repo_root: Path) -> int:
    from rag.manager import RagManager

    if not args or args[0] in {"help", "--help", "-h"}:
        print('用法: agentic-qa rag status | build | search "query"')
        return 0

    app_config = load_app_config(repo_root)
    config = app_config.rag
    manager = RagManager(repo_root, config)
    command = args[0]

    if command == "status":
        stats = manager.stats
        print(yaml.safe_dump(stats, allow_unicode=True, sort_keys=False))
        return 0
    if command == "build":
        result = manager.build_index(force_rebuild=True)
        print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False))
        return 0
    if command == "search":
        query = " ".join(args[1:]).strip()
        if not query:
            print("缺少 search query")
            return 1
        result = manager.retrieve(query)
        print(yaml.safe_dump(result.to_trace(), allow_unicode=True, sort_keys=False))
        return 0 if result.has_results and not result.has_error else 1

    print(f"未知 RAG 命令: {command}")
    return 1
