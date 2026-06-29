from __future__ import annotations

import re
from pathlib import Path

from runtime.config import load_app_config
from runtime.graph.state import QAWorkflowState
from runtime.tools.api_doc_loader import API_DOC_FILENAMES, normalize_workspace_api_docs
from runtime.tools.artifact_writer import ensure_within_directory
from runtime.tools.file_reader import read_existing_files, read_utf8
from runtime.workflow.catalog import DEFAULT_WORKFLOW_REGISTRY
from runtime.workspace import PRDWorkspace, resolve_prd_path

TASK_ANALYSIS = "analysis"
TASK_TESTCASE_GENERATION = "testcase_generation"
TASK_MVP = "mvp_analysis_testcases"
TASK_API_TEST_DRAFT = "api_test_draft"

REQUIRED_PRD_FILES = ["metadata.yml", "input/requirement.md"]
ROADMAP_CANDIDATES = [
    "docs/roadmap.md",
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
    allowed = {TASK_ANALYSIS, TASK_TESTCASE_GENERATION, TASK_MVP, TASK_API_TEST_DRAFT}
    if state.task_type not in allowed:
        state.errors.append(f"不支持的 Runtime MVP 任务类型: {state.task_type}")
        return state
    state.intent = state.task_type
    return state


def mvp_workflow_selector_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    state.record_node("mvp_workflow_selector_node")
    if state.errors:
        return state

    if state.task_type is None and state.intent:
        state.task_type = state.intent

    definition = DEFAULT_WORKFLOW_REGISTRY.definition_for_task_type(state.task_type)
    workflow_config = load_app_config(repo_root).workflow
    configured_files = workflow_config.intent_workflow_files.get(str(state.task_type)) or {
        TASK_ANALYSIS: workflow_config.mvp_analysis_workflow_files,
        TASK_TESTCASE_GENERATION: workflow_config.mvp_testcase_workflow_files,
    }.get(str(state.task_type))
    state.workflow_files = list(configured_files or definition.context_files)

    for relative_path in state.workflow_files:
        if not (repo_root / relative_path).is_file():
            state.errors.append(f"缺少 Runtime 工作流文件: {relative_path}")
    return state


def _context_files_for_task(task_type: str | None) -> list[str]:
    return list(DEFAULT_WORKFLOW_REGISTRY.definition_for_task_type(task_type).context_files)


def _resolve_context_files(repo_root: Path, task_type: str | None) -> list[str]:
    files = _context_files_for_task(task_type)
    existing_roadmap = next(
        (path for path in ROADMAP_CANDIDATES if (repo_root / path).is_file()),
        ROADMAP_CANDIDATES[0],
    )
    return [existing_roadmap if path in ROADMAP_CANDIDATES else path for path in files]


def _set_output_paths(state: QAWorkflowState, repo_root: Path, prd_path: Path) -> None:
    workspace = PRDWorkspace(prd_path)
    preview_path = workspace.artifact_preview_path(state.run_id).relative_to(repo_root).as_posix()

    if state.task_type in {TASK_ANALYSIS, TASK_MVP}:
        state.output_paths["requirement_analysis"] = preview_path
    if state.task_type in {TASK_TESTCASE_GENERATION, TASK_MVP}:
        state.output_paths["testcases"] = preview_path
    if state.task_type == TASK_API_TEST_DRAFT:
        state.output_paths["api_test_draft"] = preview_path

    if state.task_type == TASK_ANALYSIS:
        state.output_path = preview_path
    elif state.task_type == TASK_TESTCASE_GENERATION:
        state.output_path = preview_path
    elif state.task_type == TASK_API_TEST_DRAFT:
        state.output_path = preview_path


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

    if state.task_type == TASK_API_TEST_DRAFT:
        try:
            normalized_api = normalize_workspace_api_docs(repo_root, state.prd_path)
        except (OSError, ValueError) as exc:
            state.errors.append(f"API 文档归一化失败: {exc}")
            return state
        if normalized_api is not None:
            state.warnings.append(
                "已归一化 OpenAPI/Swagger 文档: "
                f"{normalized_api.copied_path.relative_to(repo_root).as_posix()} -> "
                f"{normalized_api.markdown_path.relative_to(repo_root).as_posix()}"
            )

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
    for api_doc_name in API_DOC_FILENAMES:
        raw_api_doc = prd_path / "input" / api_doc_name
        if raw_api_doc.is_file():
            state.loaded_files[raw_api_doc.relative_to(repo_root).as_posix()] = read_utf8(
                raw_api_doc
            )

    analysis_file = prd_path / "artifacts" / "requirement-analysis.md"
    analysis_relative_path = analysis_file.relative_to(repo_root).as_posix()
    if analysis_file.is_file():
        state.loaded_files[analysis_relative_path] = read_utf8(analysis_file)
    elif state.task_type in {TASK_TESTCASE_GENERATION, TASK_API_TEST_DRAFT}:
        state.warnings.append(
            "需求分析文件不存在，将基于 input/requirement.md 生成候选草稿: "
            f"{analysis_relative_path}"
        )

    testcases_file = prd_path / "artifacts" / "testcases.md"
    testcases_relative_path = testcases_file.relative_to(repo_root).as_posix()
    if testcases_file.is_file():
        state.loaded_files[testcases_relative_path] = read_utf8(testcases_file)
    elif state.task_type == TASK_API_TEST_DRAFT:
        state.warnings.append(
            "测试用例正式产物不存在，将基于需求和接口文档生成接口测试候选点: "
            f"{testcases_relative_path}"
        )

    _set_output_paths(state, repo_root, prd_path)
    return state
