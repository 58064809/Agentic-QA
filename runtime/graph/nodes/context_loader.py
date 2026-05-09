from __future__ import annotations

from pathlib import Path

from runtime.graph.state import QAWorkflowState
from runtime.tools.artifact_writer import ensure_within_directory
from runtime.tools.file_reader import read_existing_files, read_utf8

STATIC_CONTEXT_FILES = [
    "AGENTS.md",
    "COMMANDS.md",
    "docs/architecture/production-agent-runtime-roadmap.md",
    "workflows/10-runtime-testcase-generation-workflow.md",
    "workflows/02-testcase-generation-workflow.md",
    "prompts/testcase-design-prompt.md",
    "rules/testcase-rules.md",
    "rules/review-gate-rules.md",
    "rules/artifact-path-rules.md",
    "skills/test-design-skill.md",
    "knowledge/templates/testcase-template.md",
]
REQUIRED_PRD_FILES = ["metadata.yml", "requirement.md"]
OPTIONAL_PRD_FILES = ["10-analysis/requirement-analysis.md"]


def resolve_prd_path(repo_root: Path, prd_path: str) -> Path:
    path = Path(prd_path)
    return path if path.is_absolute() else repo_root / path


def context_loader_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    state.record_node("context_loader_node")
    if state.errors:
        return state

    prd_path = resolve_prd_path(repo_root, state.prd_path)
    if not prd_path.is_dir():
        state.errors.append(f"PRD 工作区不存在: {state.prd_path}")
        return state
    if not ensure_within_directory(prd_path, repo_root / "prd"):
        state.errors.append(f"PRD 工作区必须位于 prd/ 下: {state.prd_path}")
        return state

    loaded, errors = read_existing_files(repo_root, STATIC_CONTEXT_FILES)
    state.loaded_files.update(loaded)
    state.errors.extend(errors)

    for filename in REQUIRED_PRD_FILES:
        path = prd_path / filename
        relative_path = path.relative_to(repo_root).as_posix()
        if not path.is_file():
            state.errors.append(f"缺少 PRD 必需文件: {relative_path}")
            continue
        state.loaded_files[relative_path] = read_utf8(path)

    for filename in OPTIONAL_PRD_FILES:
        path = prd_path / filename
        relative_path = path.relative_to(repo_root).as_posix()
        if path.is_file():
            state.loaded_files[relative_path] = read_utf8(path)
        else:
            state.warnings.append(f"可选分析文件不存在，继续 dry-run: {relative_path}")

    state.output_path = (prd_path / "20-testcases" / "testcases.md").relative_to(
        repo_root
    ).as_posix()
    return state
