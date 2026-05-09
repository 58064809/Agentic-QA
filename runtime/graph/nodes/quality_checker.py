from __future__ import annotations

from pathlib import Path

from runtime.graph.nodes.context_loader import resolve_prd_path
from runtime.graph.state import QAWorkflowState
from runtime.tools.artifact_writer import ensure_within_directory

REQUIRED_TESTCASE_COLUMNS = ["标题", "优先级", "前置条件", "测试步骤", "预期结果"]


def testcase_quality_check_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    state.record_node("testcase_quality_check_node")
    if state.errors:
        return state

    if not state.draft_artifact:
        state.quality_errors.append("测试用例草稿为空。")
        return state

    if "needs_human_review" not in state.draft_artifact:
        state.quality_errors.append("测试用例草稿缺少 needs_human_review 状态。")

    for column in REQUIRED_TESTCASE_COLUMNS:
        if column not in state.draft_artifact:
            state.quality_errors.append(f"测试用例草稿缺少表头: {column}")

    if not state.output_path:
        state.quality_errors.append("缺少输出路径。")
        return state

    output_path = repo_root / state.output_path
    prd_path = resolve_prd_path(repo_root, state.prd_path)
    if not ensure_within_directory(output_path, prd_path):
        state.quality_errors.append("输出路径必须位于目标 PRD 工作区内。")
    if Path(state.output_path).as_posix().split("/")[-3:] != [
        prd_path.name,
        "20-testcases",
        "testcases.md",
    ]:
        state.quality_errors.append("输出路径必须是 prd/<id>/20-testcases/testcases.md。")
    return state
