from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from runtime.cli import promoter as cli
from runtime.cli.main import _print_result

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
    assert "未给出 artifact 时读取该 run 实际记录的候选产物" in content
    assert "缺省时按需求分析 + 测试用例处理" not in content


def test_cli_labels_interrupted_generation_as_waiting_for_review(capsys):
    result = SimpleNamespace(
        errors=[],
        output_path=None,
        warnings=[],
        quality_errors=[],
        run_id="run-test",
        review_status="needs_human_review",
        run_status="interrupted",
        next_action="wait_for_review",
    )

    _print_result(result, "testcase_generation")

    output = capsys.readouterr().out
    assert "候选产物已生成" in output
    assert "等待人" in output
    assert "测试用例生成完成" not in output
