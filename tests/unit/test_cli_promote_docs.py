from __future__ import annotations

from pathlib import Path

import runtime.cli as cli

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_promote_help_lists_all_artifacts(capsys):
    exit_code = cli._run_promote_command(["help"], REPO_ROOT)

    output = capsys.readouterr().out

    assert exit_code == 0
    for artifact in (
        "requirement_analysis",
        "testcases",
        "api_test_draft",
        "ui_test_draft",
        "api_discovery_report",
        "qa_report",
    ):
        assert artifact in output


def test_commands_promote_docs_describe_latest_run_default():
    content = (REPO_ROOT / "COMMANDS.md").read_text(encoding="utf-8")

    assert "api_test_draft" in content
    assert "ui_test_draft" in content
    assert "api_discovery_report" in content
    assert "qa_report" in content
    assert "缺省时优先读取目标工作区 latest run 中的 artifact" in content
    assert "缺省时按需求分析 + 测试用例处理" not in content
