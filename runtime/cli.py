"""Agentic-QA 纯自然语言 CLI 入口

用法:
    agentic-qa "你的自然语言命令"

特点:
    - 自然语言模式是主入口
    - rag / promote 等工程命令用于本地调试和闭环验证
    - Intent Layer 自动提取意图和文档来源
    - 自动进入对话循环，支持多轮会话
    - 自动写入候选产物，不直接发布正式产物
"""

from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

from runtime.config import load_app_config
from runtime.graph.app import (
    default_repo_root,
    promote_artifacts,
    run_mvp_analysis_and_testcases_workflow,
    run_mvp_testcase_generation_workflow,
    run_requirement_analysis_workflow,
)
from runtime.intent import route_user_intent
from runtime.review import ReviewDecision, ReviewIntent, process_review_gate
from runtime.schemas.runtime_result import RuntimeResult
from runtime.session import Session, SessionManager
from runtime.workspace import PRDWorkspace, default_metadata, read_yaml_mapping, write_yaml_mapping

PRD_WORKSPACE_PATH_RE = re.compile(
    r"""
    (?:
        [a-zA-Z]:\\(?:[^\s\\"']+\\)*prd\\[^\s\\"']+
        |
        prd[/\\][^\s\\"']+
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

RUN_ID_RE = re.compile(r"run-\d{8}-\d{6}-[a-z0-9]+|runtime", re.IGNORECASE)
PROMOTE_KEYWORDS = ("发布正式产物", "发布产物", "正式发布", "通过并发布", "发布吧", "promote")
APPROVE_KEYWORDS = ("通过", "确认", "approved", "confirmed", "approve")
ARTIFACT_ALIASES = {
    "requirement_analysis": ("requirement_analysis", "requirement-analysis", "需求分析"),
    "testcases": ("testcases", "testcase", "test-cases", "测试用例", "用例"),
    "qa_report": ("qa_report", "qa-report", "QA报告", "qa report"),
}

# ── 帮助提示 ──────────────────────────────────────────────────

HELP_TEXT = """用法:
    agentic-qa "你的自然语言命令"
    agentic-qa rag status
    agentic-qa rag build
    agentic-qa rag search "边界值 活动玩法"
    agentic-qa promote prd/sample-login-requirement [run_id] [testcases|requirement_analysis]

示例:
    agentic-qa "帮我分析登录需求 D:\\需求\\登录.md"
    agentic-qa "分析 prd/sample-login-requirement 并生成测试用例"
    agentic-qa "测试用例通过，发布正式产物 prd/sample-login-requirement"
    agentic-qa "处理这个飞书链接 https://xxx.feishu.cn/docx/123"

对话模式:
    # 首次执行后自动进入对话模式
    > 再补充几个边界用例
    > 分析支付模块 D:\\需求\\支付.md
    > 退出

数据目录（不提交 Git）:
    .runtime/sessions/default/   - 会话持久化
    .runtime/runs/<run_id>/      - 运行记录
"""


def _run_rag_command(args: list[str], repo_root: Path) -> int:
    from rag.config import RagConfig
    from rag.manager import RagManager

    if not args or args[0] in {"help", "--help", "-h"}:
        print('用法: agentic-qa rag status | build | search "query"')
        return 0

    app_config = load_app_config(repo_root)
    config = RagConfig.from_app_config(app_config.rag)
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


def _read_latest_run_id(workspace: PRDWorkspace) -> str | None:
    latest_path = workspace.runs_dir / "latest.yml"
    if not latest_path.is_file():
        return None
    latest = read_yaml_mapping(latest_path)
    run_id = latest.get("run_id")
    return str(run_id) if run_id else None


def _extract_run_id(value: str) -> str | None:
    match = RUN_ID_RE.search(value)
    return match.group(0) if match else None


def _artifact_keys_from_text(value: str) -> list[str]:
    keys = [
        key
        for key, aliases in ARTIFACT_ALIASES.items()
        if any(alias.lower() in value.lower() for alias in aliases)
    ]
    return keys or ["requirement_analysis", "testcases"]


def _task_type_from_artifact_keys(keys: list[str]) -> str:
    normalized = set(keys)
    if normalized == {"requirement_analysis"}:
        return "analysis"
    if normalized == {"testcases"}:
        return "testcase_generation"
    return "mvp_analysis_testcases"


def _is_promote_request(user_input: str) -> bool:
    return any(keyword in user_input for keyword in PROMOTE_KEYWORDS) and any(
        keyword in user_input for keyword in APPROVE_KEYWORDS
    )


def _approve_reviews_via_gate_for_promotion(
    repo_root: Path,
    prd_rel: str,
    run_id: str,
    artifact_keys: list[str],
    *,
    source_message: str,
    natural_language: bool,
) -> list[str]:
    if natural_language:
        gate_result = process_review_gate(
            repo_root=repo_root,
            prd_path=prd_rel,
            run_id=run_id,
            user_input=source_message,
            artifact_keys=artifact_keys,
        )
        if not gate_result.approved_for_promote:
            details = "; ".join(gate_result.errors) or gate_result.decision.reason
            raise ValueError(f"Review Gate 未批准发布: {details}")
        return gate_result.target_artifacts

    approved_keys: list[str] = []
    for key in artifact_keys:
        gate_result = process_review_gate(
            repo_root=repo_root,
            prd_path=prd_rel,
            run_id=run_id,
            user_input=source_message,
            artifact_keys=[key],
            decision=ReviewDecision(
                intent=ReviewIntent.APPROVE,
                target_artifact=key,
                confidence=1.0,
                reason="显式 promote 命令触发确定性审核通过",
            ),
        )
        if not gate_result.approved_for_promote:
            details = "; ".join(gate_result.errors) or gate_result.decision.reason
            raise ValueError(f"Review Gate 未批准发布 {key}: {details}")
        approved_keys.extend(gate_result.target_artifacts)
    return approved_keys


def _print_promote_result(result: RuntimeResult) -> None:
    if result.errors:
        print("❌ 发布失败:")
        for error in result.errors:
            print(f"   - {error}")
        return
    print("✅ 已发布正式产物")
    for key, path in result.output_paths.items():
        print(f"   - {key}: {path}")


def _run_promote(
    repo_root: Path,
    prd_rel: str,
    run_id: str | None,
    artifact_keys: list[str],
    *,
    source_message: str,
    natural_language: bool = False,
) -> RuntimeResult:
    workspace = PRDWorkspace(repo_root / prd_rel)
    selected_run_id = run_id or _read_latest_run_id(workspace)
    if not selected_run_id:
        raise ValueError(f"未找到 latest run_id: {workspace.runs_dir / 'latest.yml'}")
    approved_keys = _approve_reviews_via_gate_for_promotion(
        repo_root,
        prd_rel,
        selected_run_id,
        artifact_keys,
        source_message=source_message,
        natural_language=natural_language,
    )
    return promote_artifacts(
        prd_rel,
        selected_run_id,
        repo_root=repo_root,
        task_type=_task_type_from_artifact_keys(approved_keys),
    )


def _run_promote_command(args: list[str], repo_root: Path) -> int:
    if not args or args[0] in {"help", "--help", "-h"}:
        print(
            "用法: agentic-qa promote prd/<requirement> "
            "[run_id] [testcases|requirement_analysis]"
        )
        return 0
    prd_rel = _ensure_prd_workspace(repo_root, args[0])
    rest = " ".join(args[1:])
    run_id = _extract_run_id(rest)
    artifact_keys = _artifact_keys_from_text(rest)
    try:
        result = _run_promote(
            repo_root,
            prd_rel,
            run_id,
            artifact_keys,
            source_message="agentic-qa promote " + " ".join(args),
            natural_language=False,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"❌ {exc}")
        return 1
    _print_promote_result(result)
    return 0 if result.success else 1


def _run_natural_promote_request(
    user_input: str,
    repo_root: Path,
    *,
    fallback_prd: str | None = None,
) -> tuple[str, RuntimeResult]:
    prd_path = _extract_prd_workspace_path(user_input) or fallback_prd
    if not prd_path:
        raise ValueError("未指定 PRD 工作区，且没有可复用的上次工作区。")
    prd_rel = _ensure_prd_workspace(repo_root, prd_path)
    run_id = _extract_run_id(user_input)
    artifact_keys = _artifact_keys_from_text(user_input)
    result = _run_promote(
        repo_root,
        prd_rel,
        run_id,
        artifact_keys,
        source_message=user_input,
        natural_language=True,
    )
    return prd_rel, result


# ── Intent → 工作流映射 ───────────────────────────────────────


def _task_type_from_intent(intent: str) -> str | None:
    """将 LLM 路由意图映射到 Graph 的 task_type。"""
    mapping = {
        "mvp": "mvp_analysis_testcases",
        "requirement_analysis": "analysis",
        "testcase_generation": "testcase_generation",
        "api_test_generation": "testcase_generation",
        "ui_test_generation": "testcase_generation",
        "test_execution": "testcase_generation",
        "failure_analysis": "testcase_generation",
        "bug_draft": "testcase_generation",
        "report_generation": "testcase_generation",
        "archive": None,
    }
    return mapping.get(intent)


def _run_workflow(
    user_input: str,
    prd_path: str,
    *,
    intent: str,
    repo_root: Path,
    session: Session,
    debug: bool = False,
) -> RuntimeResult:
    """根据意图执行对应工作流。"""
    approve_write = False
    app_config = load_app_config(repo_root)
    llm_enabled = app_config.llm.enabled

    requirement_analysis_use_llm = llm_enabled and app_config.workflow.use_llm_for(
        "requirement_analysis"
    )
    testcase_generation_use_llm = llm_enabled and app_config.workflow.use_llm_for(
        "testcase_generation"
    )
    mvp_use_llm = llm_enabled and app_config.workflow.use_llm_for("mvp_analysis_testcases")

    if intent == "requirement_analysis":
        result = run_requirement_analysis_workflow(
            user_input=user_input,
            prd_path=Path(prd_path),
            repo_root=repo_root,
            approve_write=approve_write,
            record_run=True,
            use_llm=requirement_analysis_use_llm,
        )
    elif intent == "testcase_generation":
        result = run_mvp_testcase_generation_workflow(
            user_input=user_input,
            prd_path=Path(prd_path),
            repo_root=repo_root,
            approve_write=approve_write,
            record_run=True,
            use_llm=testcase_generation_use_llm,
        )
    else:
        # 兜底：MVP（需求分析 + 测试用例）
        result = run_mvp_analysis_and_testcases_workflow(
            user_input=user_input,
            prd_path=Path(prd_path),
            repo_root=repo_root,
            approve_write=approve_write,
            record_run=True,
            use_llm=mvp_use_llm,
        )

    return result


def _route_user_intent(user_input: str, repo_root: Path):
    """根据配置选择 LLM 语义路由或确定性路由。"""
    return route_user_intent(user_input, repo_root)


def _extract_prd_workspace_path(user_input: str) -> str | None:
    match = PRD_WORKSPACE_PATH_RE.search(user_input)
    if not match:
        return None
    return match.group(0).strip().rstrip("，。；,;.)>")


# ── PRD 工作区管理 ────────────────────────────────────────────


def _ensure_prd_workspace(
    repo_root: Path,
    prd_path_str: str,
) -> str:
    """确保 PRD 工作区存在，返回相对路径字符串。

    三种情况:
    1. 已经是 prd/<name> 相对路径 → 直接使用
    2. 绝对路径指向已存在的 PRD 目录 → 转换为相对路径
    3. 绝对路径指向一个源文件 → 创建 PRD 工作区
    """
    candidate = Path(prd_path_str)

    # 情况 1: 已经是 prd/<name> 或相对路径
    if not candidate.is_absolute():
        # 确保不以 prd 开头时也拼接
        if not prd_path_str.startswith("prd/"):
            prd_path_str = f"prd/{prd_path_str}"
        full = repo_root / prd_path_str
        if full.is_dir():
            return prd_path_str
        # 目录不存在，尝试用名字创建
        full.mkdir(parents=True, exist_ok=True)
        _init_workspace_metadata(full, candidate.name)
        return prd_path_str

    # 情况 2: 绝对路径，已经是目录
    if candidate.is_dir():
        try:
            rel = candidate.relative_to(repo_root)
            return rel.as_posix()
        except ValueError:
            # 不在 repo 内，创建软链接或复制目录
            return _import_external_directory(repo_root, candidate)

    # 情况 3: 绝对路径，是一个源文件
    if candidate.is_file():
        return _import_source_file(repo_root, candidate)

    # 不存在，报错
    raise FileNotFoundError(f"文件或目录不存在: {prd_path_str}")


def _workspace_name(path: Path) -> str:
    """从文件路径生成工作区名字。"""
    stem = path.stem
    # 去掉中文"需求"前缀以保持简洁
    for prefix in ("需求", "requirement", "prd_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
            break
    # 移除特殊字符
    stem = "".join(c for c in stem if c.isalnum() or c in "-_")
    return stem or "default"


def _init_workspace_metadata(workspace_dir: Path, name: str) -> None:
    """创建初始 metadata.yml。"""
    metadata = default_metadata(name, name, "agentic-qa")
    metadata_path = PRDWorkspace(workspace_dir).metadata_path
    if not metadata_path.is_file():
        write_yaml_mapping(metadata_path, metadata)


def _safe_workspace_name(value: str) -> str:
    stem = "".join(c for c in value.strip() if c.isalnum() or c in "-_")
    return stem[:80] or f"requirement-{datetime.now().strftime('%Y%m%d%H%M%S')}"


def _import_markdown_requirement(
    repo_root: Path,
    markdown: str,
    *,
    title: str = "manual-markdown-requirement",
    source_url: str | None = None,
) -> str:
    """Create a PRD workspace from already-normalized Markdown text."""
    name = _safe_workspace_name(title)
    prd_rel = f"prd/{name}"
    workspace_dir = repo_root / prd_rel
    workspace_dir.mkdir(parents=True, exist_ok=True)

    requirement_path = workspace_dir / "input/requirement.md"
    requirement_path.parent.mkdir(parents=True, exist_ok=True)
    if not requirement_path.is_file():
        requirement_path.write_text(markdown.strip() + "\n", encoding="utf-8")

    metadata = {
        **default_metadata(name, title, "agentic-qa"),
        "source_type": "feishu" if source_url else "manual_markdown",
    }
    if source_url:
        metadata["source_url"] = source_url
    metadata_path = PRDWorkspace(workspace_dir).metadata_path
    if not metadata_path.is_file():
        write_yaml_mapping(metadata_path, metadata)
    return prd_rel


def is_feishu_url(url: str) -> bool:
    from runtime.tools.feishu_fetcher import is_feishu_url as _is_feishu_url

    return _is_feishu_url(url)


def fetch_feishu_doc(url: str) -> tuple[str, str]:
    from runtime.tools.feishu_fetcher import fetch_feishu_doc as _fetch_feishu_doc

    return _fetch_feishu_doc(url)


def _import_feishu_url(repo_root: Path, url: str) -> str:
    """Fetch a Feishu document and normalize it into a PRD workspace."""
    if not is_feishu_url(url):
        raise ValueError(f"无法识别飞书文档链接: {url}")
    title, markdown = fetch_feishu_doc(url)
    if not markdown.strip():
        raise ValueError("飞书文档内容为空，无法生成 input/requirement.md")
    return _import_markdown_requirement(
        repo_root,
        markdown,
        title=title,
        source_url=url,
    )


def _looks_like_markdown_requirement(user_input: str) -> bool:
    text = user_input.strip()
    if len(text) < 20:
        return False
    return text.startswith("# ") or "\n## " in text or "\n- " in text


def _import_source_file(repo_root: Path, source_path: Path) -> str:
    """从源文件导入并创建 PRD 工作区。"""
    name = _workspace_name(source_path)
    prd_rel = f"prd/{name}"
    workspace_dir = repo_root / prd_rel
    workspace_dir.mkdir(parents=True, exist_ok=True)

    input_dir = workspace_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    if source_path.suffix.lower() in {".md", ".markdown", ".txt"}:
        dest = input_dir / "requirement.md"
    else:
        dest = input_dir / f"requirement{source_path.suffix.lower()}"
    if not dest.is_file():
        shutil.copy2(source_path, dest)

    # 创建 metadata
    _init_workspace_metadata(workspace_dir, name)

    print(f"📁 创建 PRD 工作区: {prd_rel} （来源: {source_path}）")
    return prd_rel


def _import_external_directory(repo_root: Path, external_dir: Path) -> str:
    """从外部目录导入 PRD 工作区。"""
    name = _workspace_name(external_dir)
    prd_rel = f"prd/{name}"
    workspace_dir = repo_root / prd_rel
    workspace_dir.mkdir(parents=True, exist_ok=True)

    input_dir = workspace_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    # 复制目录下的需求文档
    for ext in ("*.md", "*.pdf", "*.docx", "*.txt", "*.html"):
        for f in external_dir.glob(ext):
            dest = input_dir / f.name
            if not dest.is_file():
                shutil.copy2(f, dest)

    _init_workspace_metadata(workspace_dir, name)
    print(f"📁 导入外部工作区: {prd_rel} （来源: {external_dir}）")
    return prd_rel


# ── 结果输出 ──────────────────────────────────────────────────


def _print_result(result: RuntimeResult, intent: str) -> None:
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

    # 任务摘要
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
    """进入对话循环，等待用户自然语言输入。"""
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

        # 重置会话
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

        # 路由意图
        route = _route_user_intent(line, repo_root)

        if not route.is_valid:
            console.print(f"[red]❌ 路由失败: {'; '.join(route.errors)}[/red]")
            continue

        # 重置意图
        if route.is_reset:
            session.reset()
            console.print("🔄 会话已重置")
            continue

        # 更新 session 状态
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

        # 确保工作区
        try:
            prd_rel = _ensure_prd_workspace(repo_root, prd_path)
        except FileNotFoundError as e:
            console.print(f"[red]❌ {e}[/red]")
            continue

        # 更新 session
        session.update_meta(
            last_prd_path=prd_rel,
            last_intent=intent,
        )
        session.append_history("user", line)
        last_prd = prd_rel
        last_intent = intent

        # 执行工作流
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
        return _run_rag_command(sys.argv[2:], repo_root)
    if len(sys.argv) >= 2 and sys.argv[1] == "promote":
        return _run_promote_command(sys.argv[2:], repo_root)

    # 帮助
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

    # 路由意图。Intent Layer 会按配置选择 LLM 语义路由或确定性路由。
    route = _route_user_intent(user_input, repo_root)

    if not route.is_valid:
        print(f"❌ 路由失败: {'; '.join(route.errors)}")
        return 1

    if route.is_reset:
        session.reset()
        print("🔄 会话已重置")
        return 0

    # 确保 PRD 工作区存在
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

    # 确定意图（如果是 resume 或未识别，从 session 复用或默认 mvp）
    intent = route.intent
    if intent == "resume" or not intent:
        intent = session.meta.last_intent or "mvp"

    # 保存 session 状态
    session.update_meta(
        last_prd_path=prd_rel,
        last_intent=intent,
    )
    session.append_history("user", user_input)

    # 执行
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

    # 进入对话循环
    print('💬 继续对话（输入 "退出" 或 Ctrl+C 结束）')
    _dialogue_loop(session, repo_root)

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
