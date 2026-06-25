"""LEGACY ONLY: old langgraph_app context loader.

Merged for current runtime into mvp_context_loader and WorkflowSpec-driven nodes.
"""

from __future__ import annotations

from pathlib import Path

from runtime.config import load_app_config
from runtime.graph.state import QAWorkflowState
from runtime.tools.artifact_writer import ensure_within_directory
from runtime.tools.file_reader import read_existing_files, read_utf8
from runtime.workspace import PRDWorkspace

# ── 每种意图的上下文文件列表 ────────────────────────────────
INTENT_CONTEXT_FILES: dict[str, list[str]] = {
    "requirement_analysis": [
        "AGENTS.md",
        "COMMANDS.md",
        "workflows/01-requirement-analysis-workflow.md",
        "prompts/requirement-analysis-prompt.md",
        "rules/requirement-analysis-rules.md",
        "rules/review-gate-rules.md",
        "rules/artifact-path-rules.md",
        "skills/analysis/requirement-decomposition-skill.md",
        "skills/analysis/business-rule-extraction-skill.md",
    ],
    "testcase_generation": [
        "AGENTS.md",
        "COMMANDS.md",
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/02-testcase-generation-workflow.md",
        "prompts/testcase-design-prompt.md",
        "rules/testcase-rules.md",
        "rules/review-gate-rules.md",
        "rules/artifact-path-rules.md",
        "skills/test-design/test-design-skill.md",
        "knowledge/templates/testcase-template.md",
    ],
    "api_test_generation": [
        "AGENTS.md",
        "COMMANDS.md",
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/03-api-test-generation-workflow.md",
        "prompts/api-test-generation-prompt.md",
        "rules/testcase-rules.md",
        "rules/review-gate-rules.md",
        "rules/artifact-path-rules.md",
        "skills/test-design/test-design-skill.md",
        "knowledge/templates/testcase-template.md",
    ],
    "ui_test_generation": [
        "AGENTS.md",
        "COMMANDS.md",
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/04-ui-test-generation-workflow.md",
        "prompts/ui-test-generation-prompt.md",
        "rules/testcase-rules.md",
        "rules/review-gate-rules.md",
        "rules/artifact-path-rules.md",
        "skills/test-design/test-design-skill.md",
        "knowledge/templates/testcase-template.md",
    ],
    "test_execution": [
        "AGENTS.md",
        "COMMANDS.md",
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/05-test-execution-workflow.md",
        "prompts/test-execution-prompt.md",
    ],
    "failure_analysis": [
        "AGENTS.md",
        "COMMANDS.md",
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/06-failure-analysis-workflow.md",
        "prompts/failure-analysis-prompt.md",
    ],
    "bug_draft": [
        "AGENTS.md",
        "COMMANDS.md",
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/07-bug-draft-workflow.md",
        "prompts/bug-draft-prompt.md",
    ],
    "report_generation": [
        "AGENTS.md",
        "COMMANDS.md",
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/08-report-generation-workflow.md",
        "prompts/report-generation-prompt.md",
    ],
    "archive": [
        "AGENTS.md",
        "COMMANDS.md",
        "workflows/10-runtime-testcase-generation-workflow.md",
        "workflows/09-archive-workflow.md",
        "prompts/archive-prompt.md",
    ],
}

# 默认 fallback（无意图匹配时使用 testcase 上下文）
DEFAULT_CONTEXT_FILES = [
    "AGENTS.md",
    "COMMANDS.md",
    "workflows/10-runtime-testcase-generation-workflow.md",
    "workflows/02-testcase-generation-workflow.md",
    "prompts/testcase-design-prompt.md",
    "rules/testcase-rules.md",
    "rules/review-gate-rules.md",
    "rules/artifact-path-rules.md",
    "skills/test-design/test-design-skill.md",
    "knowledge/templates/testcase-template.md",
    "knowledge/templates/testcase-template.md",
]

# 需求类意图需要加载 PRD 目录文件
REQUIREMENT_LOADING_INTENTS = {
    "requirement_analysis",
    "testcase_generation",
    "api_test_generation",
    "ui_test_generation",
    "test_execution",
    "failure_analysis",
    "bug_draft",
    "report_generation",
}

REQUIRED_PRD_FILES = ["metadata.yml", "input/requirement.md"]


def resolve_prd_path(repo_root: Path, prd_path: str) -> Path:
    path = Path(prd_path)
    return path if path.is_absolute() else repo_root / path


def _output_path_for_intent(
    prd_path: Path,
    repo_root: Path,
    intent: str | None,
    run_id: str | None,
) -> str | None:
    """根据意图确定产物输出路径。intent=None 时默认走 testcase 路径。"""
    if intent == "archive":
        return None
    return PRDWorkspace(prd_path).artifact_preview_path(run_id).relative_to(repo_root).as_posix()


def context_loader_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    state.record_node("context_loader_node")
    if state.errors:
        return state

    workflow_config = load_app_config(repo_root).workflow
    configured_context = workflow_config.intent_context_files

    # 根据 intent 选择上下文文件列表，配置优先于内置默认值
    context_files = workflow_config.default_context_files or DEFAULT_CONTEXT_FILES
    if state.intent and state.intent in configured_context:
        context_files = configured_context[state.intent]
    elif state.intent and state.intent in INTENT_CONTEXT_FILES:
        context_files = INTENT_CONTEXT_FILES[state.intent]

    loaded, errors = read_existing_files(repo_root, context_files)
    state.loaded_files.update(loaded)
    state.errors.extend(errors)

    # 是否需要加载 PRD 文件（intent=None 时也加载，保持后向兼容）
    needs_prd = (state.intent is None) or (state.intent in REQUIREMENT_LOADING_INTENTS)

    if needs_prd:
        prd_path = resolve_prd_path(repo_root, state.prd_path)
        if not prd_path.is_dir():
            state.errors.append(f"PRD 工作区不存在: {state.prd_path}")
            return state
        if not ensure_within_directory(prd_path, repo_root / "prd"):
            state.errors.append(f"PRD 工作区必须位于 prd/ 下: {state.prd_path}")
            return state

        for filename in REQUIRED_PRD_FILES:
            path = prd_path / filename
            relative_path = path.relative_to(repo_root).as_posix()
            if not path.is_file():
                state.errors.append(f"缺少 PRD 必需文件: {relative_path}")
                continue
            state.loaded_files[relative_path] = read_utf8(path)
    else:
        # 非 PRD 类意图（如 archive）不需要 prd_path 存在
        pass

    # 设置输出路径
    if needs_prd:
        prd_path = resolve_prd_path(repo_root, state.prd_path)
        state.output_path = _output_path_for_intent(prd_path, repo_root, state.intent, state.run_id)
    else:
        state.output_path = None

    return state
