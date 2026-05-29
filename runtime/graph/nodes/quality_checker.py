from __future__ import annotations

from pathlib import Path

from runtime.graph.nodes.context_loader import resolve_prd_path
from runtime.graph.state import QAWorkflowState
from runtime.tools.artifact_writer import ensure_within_directory

# ── 每种意图的质检验证规则 ──────────────────────────────
REQUIRED_TESTCASE_COLUMNS = ["标题", "优先级", "前置条件", "测试步骤", "预期结果"]
REQUIRED_API_TEST_COLUMNS = ["接口", "方法", "预期状态码"]
REQUIRED_UI_TEST_COLUMNS = ["页面", "操作", "预期结果"]
REQUIRED_BUG_DRAFT_FIELDS = ["标题", "严重等级", "复现步骤"]

# 不需要质检的意图（跳过 quality_check_node）
SKIP_QUALITY_INTENTS = {"archive"}


def testcase_quality_check_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    state.record_node("testcase_quality_check_node")
    if state.errors:
        return state

    # ── 非生成类意图跳过质检 ──
    if state.intent in SKIP_QUALITY_INTENTS:
        return state

    # ── 没有草稿 → 错误（archive 已排除） ──
    if not state.draft_artifact:
        state.quality_errors.append("产物草稿为空。")
        return state

    # ── 根据意图执行特定检查（intent=None 时默认走 testcase 检查）──
    effective_intent = state.intent or "testcase_generation"
    if effective_intent == "testcase_generation":
        _check_testcase_format(state)
    elif effective_intent == "api_test_generation":
        _check_api_test_format(state)
    elif effective_intent == "ui_test_generation":
        _check_ui_test_format(state)
    elif effective_intent == "bug_draft":
        _check_bug_draft_format(state)
    else:
        # 其余意图只做基础检查
        _check_basic_format(state)

    # ── 输出路径检查 ──
    _check_output_path(state, repo_root)

    return state


def _check_testcase_format(state: QAWorkflowState) -> None:
    """测试用例格式检查（保留原有逻辑）。"""
    if "needs_human_review" not in state.draft_artifact:
        state.quality_errors.append("测试用例草稿缺少 needs_human_review 状态。")

    for column in REQUIRED_TESTCASE_COLUMNS:
        if column not in state.draft_artifact:
            state.quality_errors.append(f"测试用例草稿缺少表头: {column}")


def _check_api_test_format(state: QAWorkflowState) -> None:
    """API 测试格式检查。"""
    for column in REQUIRED_API_TEST_COLUMNS:
        if column not in state.draft_artifact:
            state.quality_errors.append(f"API 测试草稿缺少表头: {column}")


def _check_ui_test_format(state: QAWorkflowState) -> None:
    """UI 测试格式检查。"""
    for column in REQUIRED_UI_TEST_COLUMNS:
        if column not in state.draft_artifact:
            state.quality_errors.append(f"UI 测试草稿缺少表头: {column}")


def _check_bug_draft_format(state: QAWorkflowState) -> None:
    """缺陷草稿格式检查。"""
    for field in REQUIRED_BUG_DRAFT_FIELDS:
        if field not in state.draft_artifact:
            state.quality_errors.append(f"缺陷草稿缺少字段: {field}")


def _check_basic_format(state: QAWorkflowState) -> None:
    """基础格式检查（所有生成类意图共用）。"""
    if "needs_human_review" not in state.draft_artifact:
        state.quality_errors.append("产物草稿缺少 needs_human_review 状态。")
    if "# " not in state.draft_artifact:
        state.quality_errors.append("产物草稿缺少标题。")


def _check_output_path(state: QAWorkflowState, repo_root: Path) -> None:
    """输出路径合规性检查。"""
    if not state.output_path:
        state.quality_errors.append("缺少输出路径。")
        return

    output_path = repo_root / state.output_path
    prd_path = resolve_prd_path(repo_root, state.prd_path)
    if not ensure_within_directory(output_path, prd_path):
        state.quality_errors.append("输出路径必须位于目标 PRD 工作区内。")
