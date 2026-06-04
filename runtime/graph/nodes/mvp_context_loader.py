from __future__ import annotations

import re
from pathlib import Path

from runtime.graph.nodes.context_loader import resolve_prd_path
from runtime.graph.state import QAWorkflowState
from runtime.tools.artifact_writer import ensure_within_directory
from runtime.tools.file_reader import read_existing_files, read_utf8

TASK_ANALYSIS = "analysis"
TASK_TESTCASE_GENERATION = "testcase_generation"
TASK_MVP = "mvp_analysis_testcases"

ANALYSIS_WORKFLOW_FILES = ["workflows/01-requirement-analysis-workflow.md"]
TESTCASE_WORKFLOW_FILES = [
    "workflows/10-runtime-testcase-generation-workflow.md",
    "workflows/02-testcase-generation-workflow.md",
]
ANALYSIS_CONTEXT_FILES = [
    "AGENTS.md",
    "COMMANDS.md",
    "docs/production-agent-runtime-roadmap.md",
    "skills/registry/skills.yaml",
    "skills/core/requirement-understanding-skill.md",
    "skills/core/context-building-skill.md",
    "skills/core/rag-retrieval-skill.md",
    "skills/analysis/test-scope-decomposition-skill.md",
    "skills/analysis/risk-identification-skill.md",
    "skills/core/output-formatting-skill.md",
    "workflows/01-requirement-analysis-workflow.md",
    "prompts/requirement-analysis-prompt.md",
    "rules/requirement-analysis-rules.md",
    "rules/review-gate-rules.md",
    "rules/artifact-path-rules.md",
    "skills/analysis/requirement-decomposition-skill.md",
    "skills/analysis/business-rule-extraction-skill.md",
    "knowledge/templates/requirement-analysis-template.md",
]
TESTCASE_CONTEXT_FILES = [
    "AGENTS.md",
    "COMMANDS.md",
    "docs/production-agent-runtime-roadmap.md",
    "skills/registry/skills.yaml",
    "skills/core/requirement-understanding-skill.md",
    "skills/core/context-building-skill.md",
    "skills/core/rag-retrieval-skill.md",
    "skills/analysis/test-scope-decomposition-skill.md",
    "skills/analysis/risk-identification-skill.md",
    "skills/test-design/test-method-selection-skill.md",
    "skills/test-design/testcase-generation-skill.md",
    "skills/test-design/testcase-review-skill.md",
    "skills/core/output-formatting-skill.md",
    "workflows/10-runtime-testcase-generation-workflow.md",
    "workflows/02-testcase-generation-workflow.md",
    "prompts/testcase-design-prompt.md",
    "rules/testcase-rules.md",
    "rules/review-gate-rules.md",
    "rules/artifact-path-rules.md",
    "skills/test-design/test-design-skill.md",
    "skills/test-design/equivalence-partitioning-skill.md",
    "skills/test-design/boundary-value-analysis-skill.md",
    "skills/test-design/scenario-modeling-skill.md",
    "skills/test-design/state-transition-modeling-skill.md",
    "skills/test-design/risk-based-testing-skill.md",
    "knowledge/templates/testcase-template.md",
]
REQUIRED_PRD_FILES = ["workspace.yml", "input/requirement.md"]
ROADMAP_CANDIDATES = [
    "docs/production-agent-runtime-roadmap.md",
    "docs/architecture/production-agent-runtime-roadmap.md",
]
IMAGE_REFERENCE_RE = re.compile(
    r"!\[[^\]]*]\([^)]+\)|\.(?:png|jpe?g)\b|(?:^|[^A-Za-z0-9_])(?:media|images)[\\/]",
    re.IGNORECASE | re.MULTILINE,
)
IMAGE_IGNORED_WARNING = (
    "检测到需求文档包含图片/原型图引用；当前 Runtime 不分析图片内容，只基于 "
    "input/requirement.md 和 input/api.md 的文本生成需求分析和测试用例。请人工确认图片中"
    "是否存在未写入正文的字段、按钮、状态、弹窗、权限差异或交互规则。"
)


def mvp_command_router_node(state: QAWorkflowState) -> QAWorkflowState:
    state.record_node("mvp_command_router_node")
    allowed = {TASK_ANALYSIS, TASK_TESTCASE_GENERATION, TASK_MVP}
    if state.task_type not in allowed:
        state.errors.append(f"不支持的 Runtime MVP 任务类型: {state.task_type}")
        return state
    state.intent = state.task_type
    return state


def mvp_workflow_selector_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    state.record_node("mvp_workflow_selector_node")
    if state.errors:
        return state

    if state.task_type == TASK_ANALYSIS:
        state.workflow_files = list(ANALYSIS_WORKFLOW_FILES)
    elif state.task_type == TASK_TESTCASE_GENERATION:
        state.workflow_files = list(TESTCASE_WORKFLOW_FILES)
    else:
        state.workflow_files = [*ANALYSIS_WORKFLOW_FILES, *TESTCASE_WORKFLOW_FILES]

    for relative_path in state.workflow_files:
        if not (repo_root / relative_path).is_file():
            state.errors.append(f"缺少 Runtime 工作流文件: {relative_path}")
    return state


def _context_files_for_task(task_type: str | None) -> list[str]:
    if task_type == TASK_ANALYSIS:
        return list(ANALYSIS_CONTEXT_FILES)
    if task_type == TASK_TESTCASE_GENERATION:
        return list(TESTCASE_CONTEXT_FILES)
    return sorted({*ANALYSIS_CONTEXT_FILES, *TESTCASE_CONTEXT_FILES})


def _resolve_context_files(repo_root: Path, task_type: str | None) -> list[str]:
    files = _context_files_for_task(task_type)
    existing_roadmap = next(
        (path for path in ROADMAP_CANDIDATES if (repo_root / path).is_file()),
        ROADMAP_CANDIDATES[0],
    )
    return [
        existing_roadmap if path in ROADMAP_CANDIDATES else path
        for path in files
    ]


def _set_output_paths(state: QAWorkflowState, repo_root: Path, prd_path: Path) -> None:
    run_segment = state.run_id or "runtime"
    analysis_path = (
        prd_path / "runs" / run_segment / "analysis" / "requirement-analysis.md"
    ).relative_to(repo_root).as_posix()
    testcase_path = (
        prd_path / "runs" / run_segment / "cases" / "test-cases.md"
    ).relative_to(repo_root).as_posix()

    if state.task_type in {TASK_ANALYSIS, TASK_MVP}:
        state.output_paths["requirement_analysis"] = analysis_path
    if state.task_type in {TASK_TESTCASE_GENERATION, TASK_MVP}:
        state.output_paths["testcases"] = testcase_path

    if state.task_type == TASK_ANALYSIS:
        state.output_path = analysis_path
    elif state.task_type == TASK_TESTCASE_GENERATION:
        state.output_path = testcase_path


def _detect_requirement_images(
    state: QAWorkflowState,
    requirement_content: str,
) -> None:
    requirement_has_images = bool(IMAGE_REFERENCE_RE.search(requirement_content))
    warning = IMAGE_IGNORED_WARNING if requirement_has_images else None
    if warning:
        state.warnings.append(warning)
    state.prototype_notes.update(
        {
            "loaded": False,
            "path": None,
            "requirement_has_images": requirement_has_images,
            "warning": warning,
        }
    )


def mvp_context_loader_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    state.record_node("mvp_context_loader_node")
    if state.errors:
        return state

    prd_path = resolve_prd_path(repo_root, state.prd_path)
    if not prd_path.is_dir():
        state.errors.append(f"PRD 工作区不存在: {state.prd_path}")
        return state
    if not ensure_within_directory(prd_path, repo_root / "prd"):
        state.errors.append(f"PRD 工作区必须位于 prd/ 下: {state.prd_path}")
        return state

    loaded, errors = read_existing_files(
        repo_root,
        _resolve_context_files(repo_root, state.task_type),
    )
    state.loaded_files.update(loaded)
    state.errors.extend(errors)

    requirement_content = ""
    for filename in REQUIRED_PRD_FILES:
        path = prd_path / filename
        relative_path = path.relative_to(repo_root).as_posix()
        if not path.is_file():
            state.errors.append(f"缺少 PRD 必需文件: {relative_path}")
            continue
        content = read_utf8(path)
        state.loaded_files[relative_path] = content
        if filename == "input/requirement.md":
            requirement_content = content

    _detect_requirement_images(state, requirement_content)

    api_doc = prd_path / "input/api.md"
    if api_doc.is_file():
        state.loaded_files[api_doc.relative_to(repo_root).as_posix()] = read_utf8(api_doc)

    analysis_file = prd_path / "analysis" / "requirement-analysis.md"
    analysis_relative_path = analysis_file.relative_to(repo_root).as_posix()
    if analysis_file.is_file():
        state.loaded_files[analysis_relative_path] = read_utf8(analysis_file)
    elif state.task_type == TASK_TESTCASE_GENERATION:
        state.warnings.append(
            "需求分析文件不存在，将基于 input/requirement.md 生成测试用例草稿: "
            f"{analysis_relative_path}"
        )

    _set_output_paths(state, repo_root, prd_path)
    return state
