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
    _extract_api_doc_path,
    _extract_network_capture_path,
    _extract_prd_workspace_path,
    _is_promote_request,
    _looks_like_markdown_requirement,
)
from runtime.cli.promoter import (
    _run_natural_promote_request,
    _run_promote_command,
    _run_resume_command,
    _run_workflow,
)
from runtime.graph.app import (
    run_api_discovery_report_workflow,
    run_api_test_draft_workflow,
    run_mvp_analysis_and_testcases_workflow,
    run_mvp_testcase_generation_workflow,
    run_requirement_analysis_workflow,
    run_ui_test_draft_workflow,
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


__all__ = [
    "_ensure_prd_workspace",
    "_extract_api_doc_path",
    "_extract_network_capture_path",
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
    "run_api_discovery_report_workflow",
    "run_api_test_draft_workflow",
    "run_mvp_analysis_and_testcases_workflow",
    "run_mvp_testcase_generation_workflow",
    "run_requirement_analysis_workflow",
    "run_ui_test_draft_workflow",
]
