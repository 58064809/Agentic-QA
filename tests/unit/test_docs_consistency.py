from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from validate_docs_consistency import validate_docs_consistency  # noqa: E402


def write_file(path: Path, content: str = "placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_minimal_docs_repo(root: Path) -> Path:
    for directory in [
        "workflows",
        ".github",
        ".github/workflows",
        "docs",
        "docs/architecture",
        "agents",
        "tasks",
        "prompts",
        "rules",
        "skills",
        "knowledge",
        "knowledge/templates",
        "prd",
        "scripts",
        "tests",
        "runtime",
    ]:
        (root / directory).mkdir(parents=True, exist_ok=True)

    write_file(root / "README.md")
    write_file(root / "AGENTS.md")
    write_file(root / "COMMANDS.md")
    write_file(root / ".github/workflows/ci.yml")
    write_file(root / "docs/architecture/production-agent-runtime-roadmap.md")
    write_file(root / "docs/roadmap.md")
    write_file(root / "workflows/10-runtime-testcase-generation-workflow.md")
    write_file(root / "runtime/README.md")
    write_file(
        root / "rules/codex-output-rules.md",
        "标准完成回执模板\n变更摘要\n修改文件\n验收结果\n待人工确认\n下一步建议\n",
    )
    write_file(
        root / "knowledge/templates/codex-completion-summary-template.md",
        "变更摘要\n修改文件\n验收结果\n待人工确认\n下一步建议\n未执行命令必须说明原因\n",
    )
    return root


def test_validate_docs_consistency_accepts_current_repo():
    repo_root = Path(__file__).resolve().parents[2]

    errors = validate_docs_consistency(repo_root)

    assert not errors


def test_validate_docs_consistency_reports_missing_core_file(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    (repo_root / "README.md").unlink()

    errors = validate_docs_consistency(repo_root)

    assert any("缺少核心文件:" in error and error.endswith("README.md") for error in errors)


def test_validate_docs_consistency_reports_missing_ci_workflow(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    (repo_root / ".github/workflows/ci.yml").unlink()

    errors = validate_docs_consistency(repo_root)

    assert any(error.endswith(".github/workflows/ci.yml") for error in errors)


def test_validate_docs_consistency_reports_missing_runtime_roadmap(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    (repo_root / "docs/architecture/production-agent-runtime-roadmap.md").unlink()

    errors = validate_docs_consistency(repo_root)

    assert any(
        error.endswith("docs/architecture/production-agent-runtime-roadmap.md")
        for error in errors
    )


def test_validate_docs_consistency_reports_missing_runtime_readme(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    (repo_root / "runtime/README.md").unlink()

    errors = validate_docs_consistency(repo_root)

    assert any(error.endswith("runtime/README.md") for error in errors)


def test_validate_docs_consistency_reports_missing_codex_output_heading(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    write_file(
        repo_root / "rules/codex-output-rules.md",
        "变更摘要\n修改文件\n验收结果\n待人工确认\n下一步建议\n",
    )

    errors = validate_docs_consistency(repo_root)

    assert any("Codex 输出规则缺少关键内容: 标准完成回执模板" in error for error in errors)


def test_validate_docs_consistency_does_not_skip_path_refs_with_or(tmp_path):
    repo_root = create_minimal_docs_repo(tmp_path)
    write_file(
        repo_root / "docs/roadmap.md",
        "这里可以读取 `docs/not-exist.md` 或 `docs/roadmap.md`。\n",
    )

    errors = validate_docs_consistency(repo_root)

    assert any("docs/not-exist.md" in error for error in errors)
