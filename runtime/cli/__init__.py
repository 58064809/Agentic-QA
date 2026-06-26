"""Runtime CLI package.

The implementation is split across submodules, while this package root keeps
the historical ``import runtime.cli as cli`` helper surface stable for tests and
local integrations.
"""

from __future__ import annotations

from pathlib import Path

from runtime.cli.importer import (
    _ensure_prd_workspace,
    _import_markdown_requirement,
)
from runtime.cli.main import main
from runtime.cli.parser import (
    _extract_prd_workspace_path,
    _is_promote_request,
    _looks_like_markdown_requirement,
)
from runtime.cli.promoter import (
    _run_natural_promote_request,
    _run_promote_command,
    _run_resume_command,
)
from runtime.graph.app import (
    run_mvp_analysis_and_testcases_workflow,
    run_mvp_testcase_generation_workflow,
    run_requirement_analysis_workflow,
)
from runtime.intent import route_user_intent as _route_user_intent


def is_feishu_url(url: str) -> bool:
    from runtime.tools.feishu_fetcher import is_feishu_url as _is_feishu_url

    return _is_feishu_url(url)


def fetch_feishu_doc(url: str):
    from runtime.tools.feishu_fetcher import fetch_feishu_doc as _fetch_feishu_doc

    return _fetch_feishu_doc(url)


def _import_feishu_url(repo_root: Path, url: str) -> str:
    if not is_feishu_url(url):
        raise ValueError(f"不是飞书链接: {url}")
    document = fetch_feishu_doc(url)
    if isinstance(document, tuple):
        title, content = document
    else:
        title = document.title
        content = document.content
    return _import_markdown_requirement(
        repo_root,
        content,
        title=title,
        source_url=url,
        source_type="feishu",
    )


def _run_workflow(
    user_input: str,
    prd_path: str,
    *,
    intent: str,
    repo_root: Path,
    session: object | None = None,
    debug: bool = False,
):
    from runtime.config import load_app_config
    from runtime.session import Session

    app_config = load_app_config(repo_root)
    llm_enabled = app_config.llm.enabled and not debug
    approve_write = False
    if isinstance(session, Session):
        approve_write = session.debug_approve_preview_write

    if intent == "requirement_analysis":
        return run_requirement_analysis_workflow(
            user_input=user_input,
            prd_path=Path(prd_path),
            repo_root=repo_root,
            approve_write=approve_write,
            record_run=True,
            use_llm=llm_enabled and app_config.workflow.use_llm_for("requirement_analysis"),
        )
    if intent == "testcase_generation":
        return run_mvp_testcase_generation_workflow(
            user_input=user_input,
            prd_path=Path(prd_path),
            repo_root=repo_root,
            approve_write=approve_write,
            record_run=True,
            use_llm=llm_enabled and app_config.workflow.use_llm_for("testcase_generation"),
        )
    return run_mvp_analysis_and_testcases_workflow(
        user_input=user_input,
        prd_path=Path(prd_path),
        repo_root=repo_root,
        approve_write=approve_write,
        record_run=True,
        use_llm=llm_enabled and app_config.workflow.use_llm_for("mvp_analysis_testcases"),
    )


__all__ = [
    "_ensure_prd_workspace",
    "_extract_prd_workspace_path",
    "_import_feishu_url",
    "_import_markdown_requirement",
    "_is_promote_request",
    "_looks_like_markdown_requirement",
    "_route_user_intent",
    "_run_natural_promote_request",
    "_run_promote_command",
    "_run_resume_command",
    "_run_workflow",
    "fetch_feishu_doc",
    "is_feishu_url",
    "main",
    "run_mvp_analysis_and_testcases_workflow",
    "run_mvp_testcase_generation_workflow",
    "run_requirement_analysis_workflow",
]
