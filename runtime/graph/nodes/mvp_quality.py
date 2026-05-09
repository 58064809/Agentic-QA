from __future__ import annotations

from pathlib import Path

from runtime.graph.nodes.context_loader import resolve_prd_path
from runtime.graph.nodes.mvp_context_loader import (
    TASK_ANALYSIS,
    TASK_MVP,
    TASK_TESTCASE_GENERATION,
)
from runtime.graph.state import QAWorkflowState
from runtime.tools.artifact_writer import ensure_within_directory

REQUIRED_ANALYSIS_SECTIONS = [
    "需求概述",
    "业务规则",
    "流程拆解",
    "角色与权限",
    "数据与状态",
    "异常与边界",
    "风险点",
    "待确认问题",
]
REQUIRED_TESTCASE_COLUMNS = ["标题", "优先级", "前置条件", "测试步骤", "预期结果"]


def _check_output_path(
    state: QAWorkflowState,
    repo_root: Path,
    *,
    key: str,
    expected_suffix: list[str],
    label: str,
) -> None:
    output_path = state.output_paths.get(key)
    if not output_path:
        state.quality_errors.append(f"缺少{label}输出路径。")
        return

    prd_path = resolve_prd_path(repo_root, state.prd_path)
    absolute_output = repo_root / output_path
    if not ensure_within_directory(absolute_output, prd_path):
        state.quality_errors.append(f"{label}输出路径必须位于目标 PRD 工作区内。")
    if Path(output_path).as_posix().split("/")[-3:] != expected_suffix:
        state.quality_errors.append(
            f"{label}输出路径不符合约定: {'/'.join(expected_suffix)}"
        )


def requirement_analysis_quality_check_node(
    state: QAWorkflowState, repo_root: Path
) -> QAWorkflowState:
    if state.task_type not in {TASK_ANALYSIS, TASK_MVP}:
        return state
    state.record_node("requirement_analysis_quality_check_node")
    if state.errors:
        return state

    artifact = state.draft_artifacts.get("requirement_analysis")
    if not artifact:
        state.quality_errors.append("需求分析草稿为空。")
        return state

    if "needs_human_review" not in artifact:
        state.quality_errors.append("需求分析草稿缺少 needs_human_review 状态。")
    for section in REQUIRED_ANALYSIS_SECTIONS:
        if section not in artifact:
            state.quality_errors.append(f"需求分析草稿缺少章节: {section}")

    prd_name = resolve_prd_path(repo_root, state.prd_path).name
    _check_output_path(
        state,
        repo_root,
        key="requirement_analysis",
        expected_suffix=[prd_name, "10-analysis", "requirement-analysis.md"],
        label="需求分析",
    )
    return state


def testcase_mvp_quality_check_node(
    state: QAWorkflowState, repo_root: Path
) -> QAWorkflowState:
    if state.task_type not in {TASK_TESTCASE_GENERATION, TASK_MVP}:
        return state
    state.record_node("testcase_quality_check_node")
    if state.errors:
        return state

    artifact = state.draft_artifacts.get("testcases")
    if not artifact:
        state.quality_errors.append("测试用例草稿为空。")
        return state

    if "needs_human_review" not in artifact:
        state.quality_errors.append("测试用例草稿缺少 needs_human_review 状态。")
    for column in REQUIRED_TESTCASE_COLUMNS:
        if column not in artifact:
            state.quality_errors.append(f"测试用例草稿缺少表头: {column}")

    prd_name = resolve_prd_path(repo_root, state.prd_path).name
    _check_output_path(
        state,
        repo_root,
        key="testcases",
        expected_suffix=[prd_name, "20-testcases", "testcases.md"],
        label="测试用例",
    )
    return state
