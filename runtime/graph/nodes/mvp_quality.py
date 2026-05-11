from __future__ import annotations

import re
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
    "需求背景与目标",
    "业务范围",
    "角色与权限",
    "主流程拆解",
    "分支流程与异常流程",
    "业务规则清单",
    "数据字段与状态流转",
    "接口与依赖系统",
    "测试范围建议",
    "风险点与影响面",
    "待确认问题",
    "需求到测试覆盖映射",
]
REQUIRED_TESTCASE_COLUMNS = ["标题", "优先级", "前置条件", "测试步骤", "预期结果"]
ALLOWED_PRIORITIES = {"P0", "P1", "P2", "P3"}
PLACEHOLDER_PATTERNS = [
    "待接入 LangChain",
    "待接入 LangChain 后生成",
    "Runtime MVP Skeleton",
    "主流程验证",
    "异常输入验证",
    "待补充：基于需求主流程生成",
    "待确认账号和数据",
    "结果符合需求",
    "待补充：边界条件验证",
    "TODO",
    "占位",
]
TESTCASE_KEYWORD_GROUPS = {
    "主流程": ["主流程", "成功路径", "登录成功", "成功处理"],
    "异常": ["异常", "错误", "失败", "超时", "弱网", "依赖失败"],
    "边界": ["边界", "必填", "格式", "为空", "最大", "最小", "第 4", "第 5"],
    "权限": ["权限", "角色", "未登录", "token", "Authorization", "认证", "授权"],
    "状态": ["状态", "锁定", "过期", "取消", "失效", "完成", "流转"],
    "重复幂等": ["重复", "幂等", "并发", "防重"],
    "数据一致性": ["一致", "数据库", "落库", "字段", "日志"],
    "兼容": ["历史", "老数据", "兼容"],
    "前后端": ["前端", "页面", "展示"],
    "接口": ["接口", "HTTP", "响应码", "业务码"],
    "消息日志审计": ["消息", "通知", "日志", "审计", "埋点"],
    "回归": ["回归", "影响范围"],
}
VAGUE_QUESTION_PATTERNS = ["需求是否明确", "是否明确", "是否清楚"]


def _has_section(markdown: str, section: str) -> bool:
    pattern = re.compile(rf"^##\s+(?:\d+\.\s*)?{re.escape(section)}\s*$", re.MULTILINE)
    return bool(pattern.search(markdown))


def _contains_placeholder(markdown: str) -> list[str]:
    return [pattern for pattern in PLACEHOLDER_PATTERNS if pattern in markdown]


def _section_body(markdown: str, section: str) -> str:
    pattern = re.compile(
        rf"^##\s+(?:\d+\.\s*)?{re.escape(section)}\s*$"
        r"(?P<body>.*?)(?=^##\s+(?:\d+\.\s*)?|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(markdown)
    return match.group("body").strip() if match else ""


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(set(cell) <= {"-", ":"} for cell in cells)


def _markdown_table_rows(markdown: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if _is_separator_row(cells):
            continue
        rows.append(cells)
    return rows


def _testcase_rows(markdown: str) -> tuple[list[list[str]], list[str]]:
    lines = markdown.splitlines()
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip().startswith("| 标题 |")
        ),
        None,
    )
    if header_index is None:
        return [], []

    header = [cell.strip() for cell in lines[header_index].strip().strip("|").split("|")]
    rows: list[list[str]] = []
    for line in lines[header_index + 1 :]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if _is_separator_row(cells):
            continue
        rows.append(cells)
    return rows, header


def _substantive_line_count(markdown: str) -> int:
    count = 0
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("|---"):
            continue
        if stripped in {"**范围内**", "**范围外**"}:
            continue
        count += 1
    return count


def _pending_question_count(markdown: str) -> int:
    count = 0
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("|---"):
            continue
        if any(pattern in stripped for pattern in VAGUE_QUESTION_PATTERNS):
            continue
        if stripped.startswith(("- ", "* ", "- [ ]")):
            count += 1
            continue
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if cells and cells[0] not in {"编号", "问题"} and not _is_separator_row(cells):
                count += 1
            continue
        if "？" in stripped or "?" in stripped or "待确认" in stripped:
            count += 1
    return count


def _covered_keyword_groups(markdown: str) -> set[str]:
    covered = set()
    for group, keywords in TESTCASE_KEYWORD_GROUPS.items():
        if any(keyword in markdown for keyword in keywords):
            covered.add(group)
    return covered


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
        if not _has_section(artifact, section):
            state.quality_errors.append(f"需求分析草稿缺少章节: {section}")
    for required_term in ["业务规则", "风险点", "待确认问题", "需求到测试覆盖映射"]:
        if required_term not in artifact:
            state.quality_errors.append(f"需求分析草稿缺少关键内容: {required_term}")

    pending_body = _section_body(artifact, "待确认问题")
    if _pending_question_count(pending_body) < 3:
        state.quality_errors.append("需求分析草稿待确认问题少于 3 个具体问题。")
    if any(pattern in pending_body for pattern in VAGUE_QUESTION_PATTERNS):
        state.quality_errors.append("需求分析草稿待确认问题包含空泛表述。")

    business_rules_body = _section_body(artifact, "业务规则清单")
    business_rule_line_count = _substantive_line_count(business_rules_body)
    if (
        business_rule_line_count < 3
        or (business_rules_body.count("待补充") >= 1 and business_rule_line_count <= 3)
    ):
        state.quality_errors.append("需求分析草稿业务规则清单缺少实质规则。")

    risk_body = _section_body(artifact, "风险点与影响面")
    if _substantive_line_count(risk_body) < 3:
        state.quality_errors.append("需求分析草稿风险点与影响面不能为空。")

    mapping_body = _section_body(artifact, "需求到测试覆盖映射")
    has_mapping_table = len(_markdown_table_rows(mapping_body)) >= 2
    has_mapping_list = any(
        line.strip().startswith(("- ", "* ", "1. ")) for line in mapping_body.splitlines()
    )
    if not has_mapping_table and not has_mapping_list:
        state.quality_errors.append("需求分析草稿需求到测试覆盖映射必须包含表格或列表。")

    placeholders = _contains_placeholder(artifact)
    if placeholders:
        state.quality_errors.append(
            "需求分析草稿包含纯模板或占位内容: " + ", ".join(placeholders)
        )
    if artifact.count("待补充") >= 8:
        state.warnings.append("需求分析草稿包含较多待补充内容，请人工重点确认 PRD 信息完整性。")

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
    expected_header = "| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |"
    if expected_header not in artifact:
        state.quality_errors.append("测试用例草稿缺少固定表头。")
    rows, header = _testcase_rows(artifact)
    if "用例类型" in header:
        state.quality_errors.append("测试用例草稿表头不允许新增“用例类型”列。")
    if header and header != REQUIRED_TESTCASE_COLUMNS:
        state.quality_errors.append("测试用例草稿表格列必须严格等于固定 5 列。")

    invalid_column_rows = [index for index, row in enumerate(rows, start=1) if len(row) != 5]
    if invalid_column_rows:
        state.quality_errors.append(
            "测试用例草稿存在列数不等于 5 的用例行: "
            + ", ".join(str(index) for index in invalid_column_rows[:5])
        )

    if len(rows) < 15:
        state.quality_errors.append("测试用例草稿非表头用例少于 15 条。")
    if rows and not any(row[1] == "P0" for row in rows if len(row) > 1):
        state.quality_errors.append("测试用例草稿缺少 P0 用例。")
    invalid_priorities = sorted(
        {row[1] for row in rows if len(row) > 1 and row[1] not in ALLOWED_PRIORITIES}
    )
    if invalid_priorities:
        state.quality_errors.append(
            "测试用例草稿包含非法优先级: " + ", ".join(invalid_priorities)
        )

    covered_groups = _covered_keyword_groups(artifact)
    if len(covered_groups) < 4:
        state.quality_errors.append(
            "测试用例草稿覆盖维度不足，至少需覆盖 4 类关键场景。"
        )
    placeholders = _contains_placeholder(artifact)
    if placeholders:
        state.quality_errors.append(
            "测试用例草稿包含纯模板或占位内容: " + ", ".join(placeholders)
        )

    prd_name = resolve_prd_path(repo_root, state.prd_path).name
    _check_output_path(
        state,
        repo_root,
        key="testcases",
        expected_suffix=[prd_name, "20-testcases", "testcases.md"],
        label="测试用例",
    )
    return state
