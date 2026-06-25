"""CLI: 主入口 + 对话循环。入口函数 ``main()`` 由 runtime.cli 包 re-export。"""

from __future__ import annotations

import sys
from pathlib import Path

from runtime.cli.importer import (
    _ensure_prd_workspace,
    _import_feishu_url,
    _import_markdown_requirement,
)
from runtime.cli.parser import (
    HELP_TEXT,
    _extract_prd_workspace_path,
    _is_promote_request,
    _looks_like_markdown_requirement,
)
from runtime.cli.promoter import (
    _print_promote_result,
    _run_natural_promote_request,
    _run_promote_command,
    _run_resume_command,
    _run_workflow,
)
from runtime.cli.rag_cmds import run_rag_command
from runtime.graph.app import default_repo_root
from runtime.intent import route_user_intent
from runtime.session import Session, SessionManager

# ── 结果输出 ──────────────────────────────────────────────────


def _print_result(result, intent: str) -> None:
    """打印运行结果摘要。"""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    if result.errors:
        console.print(
            Panel(
                "\n".join(result.errors),
                title="❌ 错误",
                border_style="red",
            )
        )
        return

    intent_names = {
        "requirement_analysis": "需求分析",
        "testcase_generation": "测试用例生成",
        "mvp": "需求分析 + 测试用例",
    }
    task_name = intent_names.get(intent, intent)

    table = Table(title=f"✅ {task_name} 完成", show_header=False, box=None)
    table.add_column("属性", style="cyan")
    table.add_column("值")

    if result.output_path:
        table.add_row("输出", result.output_path)
    if result.warnings:
        for w in result.warnings[:3]:
            table.add_row("⚠️", w)
    if result.quality_errors:
        for qe in result.quality_errors[:3]:
            table.add_row("质量门", qe)
    if result.run_id:
        table.add_row("运行记录", f".runtime/runs/{result.run_id}/")

    console.print(table)
    console.print()


# ── 对话循环 ──────────────────────────────────────────────────


_DIALOGUE_EXIT_WORDS = frozenset({"退出", "exit", "quit", "q", "bye"})


def _dialogue_loop(
    session: Session,
    repo_root: Path,
    debug: bool = False,
) -> None:
    from rich.console import Console

    console = Console()
    last_intent = session.meta.last_intent
    last_prd = session.meta.last_prd_path

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n👋 再见")
            break

        if not line:
            continue
        if line.lower() in _DIALOGUE_EXIT_WORDS:
            console.print("👋 再见")
            break

        if line in ("重新开始", "重置", "新会话"):
            session.reset()
            console.print("🔄 会话已重置")
            continue

        if _is_promote_request(line):
            try:
                prd_rel, result = _run_natural_promote_request(
                    line,
                    repo_root,
                    fallback_prd=last_prd,
                )
            except (FileNotFoundError, ValueError) as e:
                console.print(f"[red]❌ {e}[/red]")
                continue
            session.update_meta(last_prd_path=prd_rel, last_intent="promote")
            session.append_history("user", line)
            _print_promote_result(result)
            session.append_history("assistant", str(result))
            last_prd = prd_rel
            last_intent = "promote"
            continue

        route = route_user_intent(line, repo_root)

        if not route.is_valid:
            console.print(f"[red]❌ 路由失败: {'; '.join(route.errors)}[/red]")
            continue

        if route.is_reset:
            session.reset()
            console.print("🔄 会话已重置")
            continue

        prd_path = route.prd_path or _extract_prd_workspace_path(line) or last_prd
        intent = route.intent or last_intent or "mvp"

        if not prd_path and route.url:
            try:
                prd_path = _import_feishu_url(repo_root, route.url)
            except ValueError as e:
                console.print(f"[red]❌ {e}[/red]")
                continue
        if not prd_path and _looks_like_markdown_requirement(line):
            prd_path = _import_markdown_requirement(repo_root, line)

        if not prd_path:
            console.print("[yellow]⚠️ 未指定需求来源，请在对话中提供文件路径或飞书链接[/yellow]")
            console.print("  示例: 帮我分析 D:\\需求\\登录.md")
            continue

        try:
            prd_rel = _ensure_prd_workspace(repo_root, prd_path)
        except FileNotFoundError as e:
            console.print(f"[red]❌ {e}[/red]")
            continue

        session.update_meta(last_prd_path=prd_rel, last_intent=intent)
        session.append_history("user", line)
        last_prd = prd_rel
        last_intent = intent

        console.print(f"\n[dim]意图: {intent} | PRD: {prd_rel}[/dim]")
        result = _run_workflow(
            user_input=line,
            prd_path=prd_rel,
            intent=intent,
            repo_root=repo_root,
            session=session,
            debug=debug,
        )
        _print_result(result, intent)
        session.append_history("assistant", str(result))


# ── 主入口 ────────────────────────────────────────────────────


def main() -> int:
    # Windows GBK 终端兼容
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    repo_root = default_repo_root()

    if len(sys.argv) >= 2 and sys.argv[1] == "rag":
        return run_rag_command(sys.argv[2:], repo_root)
    if len(sys.argv) >= 2 and sys.argv[1] == "resume":
        return _run_resume_command(sys.argv[2:], repo_root)
    if len(sys.argv) >= 2 and sys.argv[1] == "promote":
        return _run_promote_command(sys.argv[2:], repo_root)

    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h", "help"):
        print(HELP_TEXT)
        return 0

    user_input = " ".join(sys.argv[1:]).strip()
    session_manager = SessionManager(repo_root)
    session = session_manager.get_or_create("default")

    if _is_promote_request(user_input):
        try:
            prd_rel, result = _run_natural_promote_request(
                user_input,
                repo_root,
                fallback_prd=session.meta.last_prd_path,
            )
        except (FileNotFoundError, ValueError) as e:
            print(f"❌ {e}")
            return 1
        session.update_meta(last_prd_path=prd_rel, last_intent="promote")
        session.append_history("user", user_input)
        _print_promote_result(result)
        session.append_history("assistant", str(result))
        return 0 if result.success else 1

    route = route_user_intent(user_input, repo_root)

    if not route.is_valid:
        print(f"❌ 路由失败: {'; '.join(route.errors)}")
        return 1

    if route.is_reset:
        session.reset()
        print("🔄 会话已重置")
        return 0

    if route.url:
        try:
            prd_rel = _import_feishu_url(repo_root, route.url)
        except ValueError as e:
            print(f"❌ {e}")
            return 1
    elif route.prd_path or _extract_prd_workspace_path(user_input):
        try:
            prd_rel = _ensure_prd_workspace(
                repo_root,
                route.prd_path or _extract_prd_workspace_path(user_input) or "",
            )
        except FileNotFoundError as e:
            print(f"❌ {e}")
            return 1
    elif _looks_like_markdown_requirement(user_input):
        prd_rel = _import_markdown_requirement(repo_root, user_input)
    elif session.meta.last_prd_path:
        prd_rel = session.meta.last_prd_path
        print(f"📂 复用上次工作区: {prd_rel}")
    else:
        print(
            "❌ 未识别到需求文档路径。请在输入中包含 .md/.pdf 等文件路径。\n"
            '   示例: agentic-qa "帮我分析登录需求 D:\\需求\\登录.md"'
        )
        return 1

    intent = route.intent
    if intent == "resume" or not intent:
        intent = session.meta.last_intent or "mvp"

    session.update_meta(last_prd_path=prd_rel, last_intent=intent)
    session.append_history("user", user_input)

    print(f"\n🎯 意图: {intent} | 📁 PRD: {prd_rel}")
    result = _run_workflow(
        user_input=user_input,
        prd_path=prd_rel,
        intent=intent,
        repo_root=repo_root,
        session=session,
    )

    _print_result(result, intent)
    session.append_history("assistant", str(result))

    print('💬 继续对话（输入 "退出" 或 Ctrl+C 结束）')
    _dialogue_loop(session, repo_root)

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
