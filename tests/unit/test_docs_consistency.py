from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from validate_docs_consistency import (  # noqa: E402
    ARTIFACT_PREVIEW_FILES,
    ARTIFACT_SPECS,
    CORE_DIRS,
    CORE_FILES,
    RUNTIME_CONTEXT_GROUPS,
    validate_docs_consistency,
)


def write_file(path: Path, content: str = "placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def current_artifact_rules() -> str:
    lines = ["# 产物路径规则"]
    for artifact_key, spec in ARTIFACT_SPECS.items():
        lines.extend(
            [
                spec["current_path"],
                spec["review_path"],
                spec["history_index"],
                f"runs/<run-id>/{ARTIFACT_PREVIEW_FILES[artifact_key]}",
            ]
        )
    return "\n".join(lines) + "\n"


def create_minimal_docs_repo(root: Path) -> Path:
    for directory in CORE_DIRS:
        (root / directory).mkdir(parents=True, exist_ok=True)

    for file_path in CORE_FILES:
        write_file(root / file_path)

    for group in RUNTIME_CONTEXT_GROUPS:
        for file_path in group:
            write_file(root / file_path)

    write_file(
        root / "rules/agent-output-rules.md",
        "标准完成回执模板\n变更摘要\n修改文件\n验收结果\n待人工确认\n下一步建议\n",
    )
    write_file(
        root / "knowledge/templates/agent-completion-summary-template.md",
        "变更摘要\n修改文件\n验收结果\n待人工确认\n下一步建议\n未执行命令必须说明原因\n",
    )
    write_file(root / "rules/artifact-path-rules.md", current_artifact_rules())
    write_file(root / "prompts/api-test-generation-prompt.md")
    write_file(root / "prompts/ui-test-generation-prompt.md")
    return root


def test_validate_docs_consistency_accepts_current_repo():
    repo_root = Path(__file__).resolve().parents[2]

    errors = validate_docs_consistency(repo_root)

    assert not errors


def test_validate_docs_consistency_accepts_minimal_current_contract(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)

    errors = validate_docs_consistency(repo_root)

    assert not errors


def test_validate_docs_consistency_reports_missing_core_file(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    (repo_root / "README.md").unlink()

    errors = validate_docs_consistency(repo_root)

    assert any("缺少核心文件:" in error and error.endswith("README.md") for error in errors)


def test_validate_docs_consistency_reports_missing_agent_output_heading(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    write_file(
        repo_root / "rules/agent-output-rules.md",
        "变更摘要\n修改文件\n验收结果\n待人工确认\n下一步建议\n",
    )

    errors = validate_docs_consistency(repo_root)

    assert any("Agent 输出规则缺少关键内容: 标准完成回执模板" in error for error in errors)


def test_validate_docs_consistency_reports_broken_markdown_path(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    write_file(repo_root / "docs/roadmap.md", "这里引用 `docs/not-exist.md`。\n")

    errors = validate_docs_consistency(repo_root)

    assert any("docs/not-exist.md" in error for error in errors)


def test_validate_docs_consistency_reports_legacy_workflow_markdown(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    write_file(repo_root / "workflows/02-testcase-generation-workflow.md")

    errors = validate_docs_consistency(repo_root)

    assert any("存在旧 Workflow Markdown" in error for error in errors)


def test_validate_docs_consistency_reports_legacy_contract_reference(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    write_file(repo_root / "docs/roadmap.md", "当前元数据读取 prd/demo/workspace.yml。\n")

    errors = validate_docs_consistency(repo_root)

    assert any("workspace.yml" in error for error in errors)


def test_validate_docs_consistency_allows_negative_legacy_reference(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    write_file(repo_root / "docs/roadmap.md", "禁止继续使用 workspace.yml。\n")

    errors = validate_docs_consistency(repo_root)

    assert not errors


def test_validate_docs_consistency_reports_duplicate_prompt(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    write_file(repo_root / "prompts/api-test-generation.md")

    errors = validate_docs_consistency(repo_root)

    assert any("存在重复 Prompt 正文" in error for error in errors)


def test_validate_docs_consistency_reports_missing_runtime_context_file(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    target = repo_root / "prompts/testcase-design-prompt.md"
    target.unlink()

    errors = validate_docs_consistency(repo_root)

    assert any("Runtime 上下文引用不存在的文件" in error and target.name in error for error in errors)


def test_validate_docs_consistency_reports_workspace_contract_drift(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    write_file(repo_root / "rules/artifact-path-rules.md", "# 产物路径规则\n")

    errors = validate_docs_consistency(repo_root)

    assert any("未覆盖 Runtime 路径契约" in error for error in errors)


def test_validate_docs_consistency_ignores_backup_and_prd_markdown(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    write_file(repo_root / "README_备份.md", "旧备份引用 `docs/not-exist.md`。\n")
    write_file(repo_root / "prd/demo/runs/run-1/output.md", "运行产物引用 `docs/not-exist.md`。\n")

    errors = validate_docs_consistency(repo_root)

    assert not errors
