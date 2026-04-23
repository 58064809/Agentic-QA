from __future__ import annotations

from typing import Any

SUMMARY_LIMITS = {
    "requirement_conclusion": 5,
    "business_objects": 8,
    "roles_permissions": 8,
    "page_prototype_coverage": 12,
    "funds_model": 10,
    "state_model": 8,
    "core_flows": 8,
    "exception_flows": 8,
    "risk_list": 10,
    "case_groups": 10,
    "requirement_items": 18,
    "business_rules": 18,
    "test_focus": 18,
    "risks": 12,
    "open_questions": 10,
    "acceptance_criteria": 12,
    "next_actions": 8,
    "test_cases": 12,
}


def _section(title: str, body: str | list[str]) -> str:
    if isinstance(body, list):
        if not body:
            return f"## {title}\n无"
        return f"## {title}\n" + "\n".join(f"- {item}" for item in body)
    return f"## {title}\n{body or '无'}"


def _numbered(items: list[str]) -> list[str]:
    return [f"{index}、{item}" for index, item in enumerate(items, start=1)]


def _numbered_for_mode(items: list[str], *, full: bool, limit: int) -> list[str]:
    if full:
        return _numbered(items)

    visible = items[:limit]
    result = _numbered(visible)
    hidden_count = len(items) - len(visible)
    if hidden_count > 0:
        result.append(f"... 还有 {hidden_count} 条，已保存到完整 Markdown 文件")
    return result


def _basis_lines(analysis_basis: dict[str, Any]) -> list[str]:
    docs = analysis_basis.get("requirement_docs", [])
    prototypes = analysis_basis.get("prototype_assets", [])
    package = analysis_basis.get("requirement_package") or {}
    lines: list[str] = []
    if package:
        lines.append(f"需求包：{package.get('relative_root') or package.get('name')}（{package.get('matched_by', 'matched')}）")
    lines.append("需求文档：" + ("、".join(docs) if docs else "未发现"))
    lines.append("原型/设计稿：" + ("、".join(prototypes) if prototypes else "未发现"))
    return lines


def _priority_lines(result: dict[str, list[str]], *, full: bool) -> list[str]:
    lines: list[str] = []
    for priority in ("P0", "P1", "P2"):
        items = result.get(priority, [])
        if not items:
            continue
        visible = items if full else items[:4]
        lines.append(f"{priority}：")
        lines.extend(f"{priority}-{index}、{item}" for index, item in enumerate(visible, start=1))
        hidden_count = len(items) - len(visible)
        if hidden_count > 0:
            lines.append(f"{priority}：... 还有 {hidden_count} 条，已保存到完整 Markdown 文件")
    return lines


def _escape_markdown_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _render_cases_table(columns: list[str], cases: list[dict[str, Any]]) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for case in cases:
        lines.append("| " + " | ".join(_escape_markdown_cell(case.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


def format_requirement_analysis(result: dict[str, Any], *, full: bool = False) -> str:
    sections = [
        "# 需求分析结论",
        _section("分析依据", _basis_lines(result.get("analysis_basis", {}))),
        _section(
            "结论摘要",
            _numbered_for_mode(
                result.get("requirement_conclusion", []),
                full=full,
                limit=SUMMARY_LIMITS["requirement_conclusion"],
            ),
        ),
        _section(
            "业务对象",
            _numbered_for_mode(result.get("business_objects", []), full=full, limit=SUMMARY_LIMITS["business_objects"]),
        ),
        _section(
            "角色与权限",
            _numbered_for_mode(result.get("roles_permissions", []), full=full, limit=SUMMARY_LIMITS["roles_permissions"]),
        ),
        _section(
            "页面与原型覆盖",
            _numbered_for_mode(
                result.get("page_prototype_coverage", []),
                full=full,
                limit=SUMMARY_LIMITS["page_prototype_coverage"],
            ),
        ),
        _section(
            "资金与金额模型",
            _numbered_for_mode(result.get("funds_model", []), full=full, limit=SUMMARY_LIMITS["funds_model"]),
        ),
        _section(
            "状态机",
            _numbered_for_mode(result.get("state_model", []), full=full, limit=SUMMARY_LIMITS["state_model"]),
        ),
        _section(
            "核心业务流",
            _numbered_for_mode(result.get("core_flows", []), full=full, limit=SUMMARY_LIMITS["core_flows"]),
        ),
        _section(
            "异常与边界流",
            _numbered_for_mode(result.get("exception_flows", []), full=full, limit=SUMMARY_LIMITS["exception_flows"]),
        ),
        _section("P0/P1/P2 测试重点", _priority_lines(result.get("priority_test_focus", {}), full=full)),
        _section(
            "主要风险",
            _numbered_for_mode(result.get("risk_list", result.get("risks", [])), full=full, limit=SUMMARY_LIMITS["risk_list"]),
        ),
        _section(
            "待确认项",
            _numbered_for_mode(result.get("open_questions", []), full=full, limit=SUMMARY_LIMITS["open_questions"]),
        ),
        _section(
            "建议用例分组",
            _numbered_for_mode(result.get("case_groups", []), full=full, limit=SUMMARY_LIMITS["case_groups"]),
        ),
        _section(
            "验收口径",
            _numbered_for_mode(result.get("acceptance_criteria", []), full=full, limit=SUMMARY_LIMITS["acceptance_criteria"]),
        ),
        _section(
            "建议下一步",
            _numbered_for_mode(result.get("next_actions", []), full=full, limit=SUMMARY_LIMITS["next_actions"]),
        ),
    ]

    if full:
        sections.append(
            _section(
                "抽取到的需求条目",
                _numbered_for_mode(result.get("requirement_items", []), full=True, limit=SUMMARY_LIMITS["requirement_items"]),
            )
        )
        sections.append(
            _section(
                "原始业务规则",
                _numbered_for_mode(result.get("business_rules", []), full=True, limit=SUMMARY_LIMITS["business_rules"]),
            )
        )

    return "\n\n".join(sections)


def format_test_cases(result: dict[str, Any], *, full: bool = False) -> str:
    columns = result.get("columns", [])
    cases = result.get("cases", [])
    visible_cases = cases if full else cases[:SUMMARY_LIMITS["test_cases"]]
    table = _render_cases_table(columns, visible_cases) if columns and cases else result.get("markdown_table", "")
    hidden_count = len(cases) - len(visible_cases)
    if hidden_count > 0:
        table = table + f"\n\n... 还有 {hidden_count} 条，已保存到完整 Markdown 文件"

    guidance = result.get("automation_guidance", {})

    return "\n\n".join(
        [
            "# 测试用例",
            _section("分析依据", _basis_lines(result.get("analysis_basis", {}))),
            _section("生成策略", _numbered(result.get("generation_strategy", []))),
            _section("建议用例分组", _numbered(result.get("case_groups", []))),
            _section("自动化候选规则", _numbered(guidance.get("automation_candidate_rules", []))),
            _section("测试反模式提醒", _numbered(guidance.get("testing_anti_patterns", []))),
            _section("待确认项", _numbered(result.get("open_questions", []))),
            _section("用例统计", f"共 {result.get('case_count', 0)} 条"),
            table,
        ]
    )


def format_script_generation(result: dict[str, Any], *, full: bool = False) -> str:
    script = result.get("script_content", "")
    language = result.get("script_language", "python")
    return "\n\n".join(
        [
            "# pytest 脚本草稿",
            _section("分析依据", _basis_lines(result.get("analysis_basis", {}))),
            _section("待确认项", _numbered(result.get("open_questions", []))),
            _section("自动化检查清单", _numbered(result.get("automation_checklist", []))),
            _section("建议文件名", result.get("recommended_file_name", "")),
            f"```{language}\n{script}```",
        ]
    )


def format_result_analysis(result: dict[str, Any], *, full: bool = False) -> str:
    return "\n\n".join(
        [
            "# pytest 结果分析",
            _section("问题类型", result.get("error_type", "unknown")),
            _section("置信度", str(result.get("confidence", ""))),
            _section("pytest 摘要", result.get("pytest_summary", "")),
            _section("证据", _numbered(result.get("evidence", []))),
            _section("失败位置", _numbered(result.get("failure_locations", []))),
            _section("Flaky 线索", _numbered(result.get("flaky_signals", []))),
            _section("可能原因", _numbered(result.get("possible_causes", []))),
            _section("下一步排查", _numbered(result.get("next_actions", []))),
            _section("原始摘要", result.get("summary", "")),
        ]
    )


def format_test_execution(execution_result: dict[str, Any], analysis_result: dict[str, Any] | None, *, full: bool = False) -> str:
    status = "通过" if execution_result.get("exit_code") == 0 else "失败"
    parts = [
        "# pytest 执行结果",
        _section("执行命令", execution_result.get("command", "")),
        _section("执行目录", execution_result.get("cwd", "")),
        _section("执行状态", f"{status}，exit_code={execution_result.get('exit_code')}"),
    ]
    if analysis_result:
        parts.append(_section("结果判断", analysis_result.get("error_type", "unknown")))
        if analysis_result.get("pytest_summary"):
            parts.append(_section("pytest 摘要", analysis_result.get("pytest_summary", "")))
        if analysis_result.get("evidence"):
            parts.append(_section("证据", _numbered(analysis_result.get("evidence", []))))
        if analysis_result.get("flaky_signals"):
            parts.append(_section("Flaky 线索", _numbered(analysis_result.get("flaky_signals", []))))
        parts.append(_section("建议动作", _numbered(analysis_result.get("next_actions", []))))
    stdout = execution_result.get("stdout", "").strip()
    stderr = execution_result.get("stderr", "").strip()
    if stdout:
        parts.append(_section("stdout", stdout if full else stdout[-1200:]))
    if stderr:
        parts.append(_section("stderr", stderr if full else stderr[-1200:]))
    return "\n\n".join(parts)


def format_log_analysis(result: dict[str, Any], *, full: bool = False) -> str:
    summary = [
        f"关键字：{result.get('keyword', '')}",
        f"搜索文件数：{result.get('searched_files', 0)}",
        f"命中条数：{result.get('match_count', 0)}",
    ]
    if result.get("error"):
        summary.append(f"错误：{result['error']}")
    return "\n\n".join(
        [
            "# 日志分析结果",
            _section("搜索概要", summary),
            _section("命中明细", result.get("matches", [])),
        ]
    )


def format_skill_result(
    intent_name: str,
    skill_result: dict[str, Any],
    analysis_result: dict[str, Any] | None = None,
    *,
    full: bool = False,
) -> str:
    if intent_name == "requirement_analysis":
        return format_requirement_analysis(skill_result, full=full)
    if intent_name == "test_case_generation":
        return format_test_cases(skill_result, full=full)
    if intent_name == "script_generation":
        return format_script_generation(skill_result, full=full)
    if intent_name == "result_analysis":
        return format_result_analysis(skill_result, full=full)
    if intent_name == "test_execution":
        return format_test_execution(skill_result, analysis_result, full=full)
    if intent_name == "log_analysis":
        return format_log_analysis(skill_result, full=full)
    return str(skill_result)
