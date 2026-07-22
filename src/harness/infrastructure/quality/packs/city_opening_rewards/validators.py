from __future__ import annotations

import re

from harness.infrastructure.quality.packs.city_opening_rewards.rules import (
    LOW_PARTICIPANT_PATTERN,
    TESTCASE_HEADERS,
    _asserts_combat_classification,
    _asserts_content_count_or_validity,
    _asserts_effective_activity_observation,
    _asserts_partial_combat_product_outcome,
    _asserts_positive_content_count,
    _asserts_positive_reward,
    _asserts_unsourced_combat_ui,
    _explicit_new_old_player_count,
    _formal_reward_config,
    _has_circle_participant_dedup_evidence,
    _has_complete_combat_evidence,
    _has_content_four_conditions,
    _has_reward_six_conditions,
    _has_unsourced_reward_config_display,
    _incompatible_reward_examples,
    _is_combat_case,
    _is_coverage_header,
    _is_growth_fund_case,
    _is_growth_tier_case,
    _is_missing_reward_condition_case,
    _is_reward_condition_case,
    _is_untriggerable_growth_ranking,
    _markdown_cells,
    _requires_unconfirmed_content_judgment,
    _row_covers_reward_config,
    _source_has_combat_definition,
    _source_has_distinct_activity_scopes,
    _unsupported_implementation_terms,
)


def _quality_check(
    artifact: str,
    content: str,
    *,
    source_corpus: str | None = None,
) -> None:
    if not content.strip():
        raise ValueError(f"{artifact} candidate is empty")
    if artifact == "requirement_analysis":
        required_sections = ("## 来源", "## 已确认", "## 待确认")
        missing_sections = [section for section in required_sections if section not in content]
        if missing_sections:
            raise ValueError(
                f"requirement_analysis candidate misses required sections: {missing_sections}"
            )
        if "# 测试用例" in content or "| 用例ID |" in content:
            raise ValueError("requirement_analysis candidate must not embed testcases")
        if source_corpus is not None:
            unsupported = _unsupported_implementation_terms(content, source_corpus)
            if unsupported:
                raise ValueError(
                    "requirement_analysis contains implementation details absent from sources: "
                    f"{unsupported}"
                )
        normalized_source = (source_corpus or "").replace(" ", "")
        if "约50%" in normalized_source and "开发计算建议" in normalized_source:
            confirmed = content.split("## 已确认", 1)[1].split("\n## ", 1)[0]
            if "获奖人数比例" in confirmed and not (
                "约" in confirmed
                and "建议" in confirmed
                and any(term in confirmed for term in ("非确定", "待确认", "未确认"))
            ):
                raise ValueError(
                    "requirement_analysis must preserve '约50%' and calculation/rounding "
                    "as non-final suggestions, not confirmed fixed rules"
                )
    if artifact == "testcases":
        missing = [header for header in TESTCASE_HEADERS if header not in content]
        if missing:
            raise ValueError(f"testcases candidate misses required columns: {missing}")
        rows = [_markdown_cells(line) for line in content.splitlines()]
        header_index = next(
            (index for index, cells in enumerate(rows) if cells == list(TESTCASE_HEADERS)),
            None,
        )
        if header_index is None:
            raise ValueError("testcases candidate has no exact ordered 11-column header row")
        coverage_index = next(
            (
                index
                for index, line in enumerate(content.splitlines())
                if index > header_index and line.lstrip().startswith("#") and "覆盖矩阵" in line
            ),
            None,
        )
        if coverage_index is None:
            raise ValueError("testcases candidate has no coverage matrix section")
        main_lines = content.splitlines()[header_index + 2 : coverage_index]
        invalid_line_numbers = [
            header_index + 3 + offset
            for offset, line in enumerate(main_lines)
            if line.strip()
            and not line.strip().startswith("|")
            and not line.strip().startswith(">")
        ]
        if invalid_line_numbers:
            raise ValueError(
                "testcases candidate contains multiline or non-table content inside main table; "
                f"physical lines: {invalid_line_numbers[:10]}; replace cell newlines with <br>"
            )
        data_rows = [_markdown_cells(line) for line in main_lines if line.strip().startswith("|")]
        if any(len(row) != len(TESTCASE_HEADERS) for row in data_rows):
            raise ValueError("testcases candidate contains a row that is not exactly 11 columns")
        if not data_rows or not any(row[0] and row[2] for row in data_rows):
            raise ValueError("testcases candidate has no valid 11-column data row")
        coverage_rows = [
            _markdown_cells(line)
            for line in content.splitlines()[coverage_index + 1 :]
            if line.strip().startswith("|")
        ]
        if (
            len(coverage_rows) < 3
            or not _is_coverage_header(coverage_rows[0])
            or not any(len(row) == 3 and all(row) for row in coverage_rows[2:])
        ):
            raise ValueError(
                "coverage matrix has no valid mapping; expected a three-column header, divider, "
                "and at least one non-empty mapping row inside the same testcases Markdown"
            )
        incomplete_coverage = [
            row[0]
            for row in coverage_rows[2:]
            if len(row) == 3
            and any(
                term in " ".join(row)
                for term in ("暂无", "未覆盖", "待补充", "需补充", "后续设计", "仍需补充")
            )
        ]
        if incomplete_coverage:
            raise ValueError(
                f"coverage matrix contains incomplete placeholder mappings: {incomplete_coverage}"
            )
        ranged_coverage_ids = [
            row[1]
            for row in coverage_rows[2:]
            if len(row) == 3 and re.search(r"TC-[A-Za-z0-9-]*\d+\s*[~～]\s*\d+", row[1])
        ]
        if ranged_coverage_ids:
            raise ValueError(
                "coverage matrix must enumerate actual testcase IDs instead of range shorthand: "
                f"{ranged_coverage_ids}"
            )
        if source_corpus is not None:
            semantic_errors: list[str] = []
            coverage_mapping_text = "\n".join(
                " ".join(row) for row in coverage_rows[2:] if len(row) == 3
            )
            unsupported = _unsupported_implementation_terms(content, source_corpus)
            if unsupported:
                semantic_errors.append(
                    f"remove implementation observations absent from sources: {unsupported}"
                )
            if "活动期的起止时间或重置规则" in source_corpus:
                invented_activity_periods = [
                    row[0]
                    for row in data_rows
                    if "活动期" in " ".join(row)
                    and re.search(r"20\d{2}-\d{2}-\d{2}", " ".join(row))
                ]
                if invented_activity_periods:
                    semantic_errors.append(
                        "activity-period dates are unconfirmed and cannot be invented as fixed "
                        f"test data: {invented_activity_periods}"
                    )
            if "领取奖励条件" in source_corpus:
                reward_coverage_requirements = (
                    ("报名", ("报名",)),
                    ("核销", ("核销",)),
                    ("获奖名单", ("获奖名单",)),
                    ("趣看动态", ("趣看", "发布动态")),
                    ("#今天一起开局", ("#今天一起开局", "话题")),
                    ("@交子立方官方号", ("@交子立方", "@官方号")),
                )
                if all(
                    any(alias in source_corpus for alias in aliases)
                    for _label, aliases in reward_coverage_requirements
                ):
                    missing_reward_coverage = [
                        label
                        for label, aliases in reward_coverage_requirements
                        if not any(alias in coverage_mapping_text for alias in aliases)
                    ]
                    if missing_reward_coverage:
                        semantic_errors.append(
                            "coverage matrix must explicitly map all six sourced reward "
                            "conditions; "
                            f"missing mappings: {missing_reward_coverage}"
                        )
                invented_reward_coverage = [
                    row[0]
                    for row in coverage_rows[2:]
                    if len(row) == 3
                    and "奖励" in row[0]
                    and any(term in row[2] for term in ("发放", "到账", "领取奖励", "领取成功"))
                    and "处理与时机待确认" not in row[2]
                ]
                if invented_reward_coverage:
                    semantic_errors.append(
                        "reward-condition coverage must map eligibility without fixed payout "
                        f"outcomes: {invented_reward_coverage}"
                    )
                invented_reward_observations = [
                    row[0]
                    for row in data_rows
                    if _is_reward_condition_case(row)
                    and "不断言未定义界面、提示或发放记录" not in " ".join((row[8], row[9]))
                    and any(
                        term in " ".join((row[8], row[9]))
                        for term in (
                            "提示",
                            "界面",
                            "奖励列表",
                            "获奖名单",
                            "显示0元",
                            "金额",
                            "发放记录",
                            "发放成功",
                            "发放奖励",
                            "奖励发放",
                            "无奖励",
                            "奖励到账",
                            "到账通知",
                            "可领奖状态",
                            "领取成功",
                            "领取失败",
                            "领取状态",
                            "已领取",
                            "错误码",
                            "奖励入口",
                            "按钮文案",
                            "不可领取",
                            "不发放",
                        )
                    )
                ]
                if invented_reward_observations:
                    semantic_errors.append(
                        "missing reward-condition cases must assert only the sourced condition "
                        "failure, not an undefined UI, prompt, list, or amount observation: "
                        f"{invented_reward_observations}"
                    )
                unsafe_partial_reward_cases = [
                    row[0]
                    for row in data_rows
                    if _is_reward_condition_case(row)
                    and not _has_reward_six_conditions(row)
                    and not any(
                        term in row[8]
                        for term in (
                            "不单独推导最终奖励资格",
                            "不满足来源中要求同时成立的全部领取条件",
                        )
                    )
                ]
                if unsafe_partial_reward_cases:
                    semantic_errors.append(
                        "a single reward condition may only establish its own input fact; it "
                        "cannot imply full eligibility or UI behavior: "
                        f"{unsafe_partial_reward_cases}"
                    )
                misclassified_missing_reward_cases = [
                    row[0]
                    for row in data_rows
                    if _is_missing_reward_condition_case(row)
                    and "不满足来源中要求同时成立的全部领取条件" not in row[8]
                ]
                if misclassified_missing_reward_cases:
                    semantic_errors.append(
                        "a missing reward condition cannot be normalized as a satisfied input "
                        f"fact: {misclassified_missing_reward_cases}"
                    )
                incomplete_reward_evidence = [
                    row[0]
                    for row in data_rows
                    if _asserts_positive_reward(row) and not _has_reward_six_conditions(row)
                ]
                if incomplete_reward_evidence:
                    semantic_errors.append(
                        "a positive reward result requires evidence for all six sourced领取条件; "
                        f"incomplete cases: {incomplete_reward_evidence}"
                    )
            if _source_has_distinct_activity_scopes(source_corpus):
                merged_scope_questions = [
                    row[0]
                    for row in data_rows
                    if "有效活动" in " ".join(row)
                    and any(term in row[10] for term in ("是否统一", "是否合并", "口径统一"))
                ]
                if merged_scope_questions:
                    semantic_errors.append(
                        "reward-stage and growth-fund activity scopes are separately confirmed; "
                        f"do not reopen them as a merge question: {merged_scope_questions}"
                    )
                invented_activity_observations = [
                    row[0]
                    for row in data_rows
                    if _asserts_effective_activity_observation(row)
                    and "产品标记、计数入口与观察点待确认" not in row[10]
                    and "奖励场次四条件与成长金三条件分别按来源执行" not in row[10]
                ]
                if invented_activity_observations:
                    semantic_errors.append(
                        "effective-activity definitions do not establish a product module, "
                        "marker, list, or observation point: "
                        f"{invented_activity_observations}"
                    )
            if "最低核销人数" in source_corpus and "10人" in source_corpus:
                invalid_low_count_cases = []
                for row in data_rows:
                    scenario = " ".join((row[2], row[5], row[6], row[7]))
                    non_executable = " ".join((row[2], row[7], row[8], row[10]))
                    low_participant_case = bool(LOW_PARTICIPANT_PATTERN.search(scenario)) or (
                        "低于最低核销人数" in scenario
                        or (
                            "核销" in scenario
                            and any(term in scenario for term in ("低于10", "<10"))
                        )
                    )
                    if low_participant_case and not (
                        any(
                            term in non_executable
                            for term in ("不可执行", "不执行", "仅作数学说明")
                        )
                        and row[7].strip() in {"-", "无", "不执行"}
                    ):
                        invalid_low_count_cases.append(row[0])
                if invalid_low_count_cases:
                    semantic_errors.append(
                        "low-count cases below the confirmed minimum verification count "
                        "must be non-executable notes without product steps or outcomes: "
                        f"{invalid_low_count_cases}"
                    )
                unsafe_low_count_outcomes = [
                    row[0]
                    for row in data_rows
                    if (
                        bool(LOW_PARTICIPANT_PATTERN.search(" ".join(row)))
                        or "低于最低核销人数" in " ".join(row)
                        or (
                            "核销" in " ".join(row)
                            and any(term in " ".join(row) for term in ("低于10", "<10"))
                        )
                    )
                    and any(
                        term in " ".join((row[8], row[9]))
                        for term in ("显示", "提示", "不计入", "不触发", "奖励结果")
                    )
                    and not any(
                        term in row[9]
                        for term in (
                            "不产生产品结果断言",
                            "不产生奖金池或奖励结果断言",
                        )
                    )
                ]
                if unsafe_low_count_outcomes:
                    semantic_errors.append(
                        "below-minimum notes cannot assert an undefined product display or "
                        f"reward outcome: {unsafe_low_count_outcomes}"
                    )
                low_new_old_examples = [
                    row[0]
                    for row in data_rows
                    if (count := _explicit_new_old_player_count(row)) is not None
                    and count < 10
                    and row[7].strip() not in {"-", "无", "不执行"}
                ]
                if low_new_old_examples:
                    semantic_errors.append(
                        "explicit new/old player examples below the confirmed minimum must be "
                        f"non-executable: {low_new_old_examples}"
                    )
                unsafe_low_count_coverage = [
                    row[0]
                    for row in coverage_rows[2:]
                    if len(row) == 3
                    and any(term in row[0] for term in ("获奖人数计算", "获奖人数计算与取整"))
                    and "不可执行数学说明" not in row[2]
                ]
                if unsafe_low_count_coverage:
                    semantic_errors.append(
                        "coverage for below-minimum rounding examples must identify them as "
                        f"non-executable suggestion notes: {unsafe_low_count_coverage}"
                    )
            normalized_source = source_corpus.replace(" ", "")
            if "约50%" in normalized_source and "开发计算建议" in normalized_source:
                fixed_suggestion_cases = []
                for row in data_rows:
                    scenario = " ".join((row[2], row[5], row[6], row[7]))
                    result = " ".join((row[8], row[9]))
                    pending = row[10].strip()
                    uses_suggestion = "50%" in scenario or any(
                        term in " ".join(row)
                        for term in (
                            "预计获奖人数",
                            "向上取整",
                            "向下取整",
                            "四舍五入",
                            "展示取整",
                            "≥0.5向上",
                            "<0.5向下",
                        )
                    )
                    asserts_fixed_result = bool(re.search(r"\d", result)) and not any(
                        term in result for term in ("若采用", "按建议", "待确认", "不可执行")
                    )
                    preserves_uncertainty = pending not in {"", "-", "无", "无。"} and any(
                        term in pending for term in ("获奖", "比例", "50%", "取整", "建议")
                    )
                    if uses_suggestion and (asserts_fixed_result or not preserves_uncertainty):
                        fixed_suggestion_cases.append(row[0])
                if fixed_suggestion_cases:
                    semantic_errors.append(
                        "approximate ratios and calculation/rounding suggestions must not become "
                        f"fixed testcase assertions without an explicit pending condition: "
                        f"{fixed_suggestion_cases}"
                    )
            invalid_combat_cases = []
            for row in data_rows:
                scenario = " ".join((row[2], row[5], row[6], row[7]))
                expected = row[8]
                if any(
                    term in scenario for term in ("非两队", "个人对个人", "多人积分排名")
                ) and any(term in expected for term in ("非对抗", "普通文案", "不展示")):
                    invalid_combat_cases.append(row[0])
            if invalid_combat_cases:
                semantic_errors.append(
                    "not being a two-team event does not prove a scenario is non-combat; "
                    "negate the three sourced combat conditions independently: "
                    f"{invalid_combat_cases}"
                )
            if _source_has_combat_definition(source_corpus):
                incomplete_combat_cases = [
                    row[0]
                    for row in data_rows
                    if _asserts_combat_classification(row)
                    and not _has_complete_combat_evidence(row)
                ]
                if incomplete_combat_cases:
                    semantic_errors.append(
                        "combat classification requires all three sourced conditions in the same "
                        f"case; incomplete cases: {incomplete_combat_cases}"
                    )
                contradictory_complete_combat_cases = [
                    row[0]
                    for row in data_rows
                    if _has_complete_combat_evidence(row)
                    and any(
                        term in row[8]
                        for term in (
                            "不按对抗类",
                            "不归类为对抗类",
                            "非对抗类",
                            "不满足对抗类定义",
                        )
                    )
                ]
                if contradictory_complete_combat_cases:
                    semantic_errors.append(
                        "complete evidence for all three sourced combat conditions cannot yield "
                        f"a negative classification: {contradictory_complete_combat_cases}"
                    )
                combat_reward_observations = [
                    row[0]
                    for row in data_rows
                    if _is_combat_case(row)
                    and "奖励" in " ".join((row[8], row[9]))
                    and "若采用来源中的展示建议" not in row[8]
                ]
                if combat_reward_observations:
                    semantic_errors.append(
                        "combat classification evidence must contain the three sourced activity "
                        f"facts, not reward outcomes: {combat_reward_observations}"
                    )
                unsafe_partial_combat_cases = [
                    row[0]
                    for row in data_rows
                    if _is_combat_case(row)
                    and not _has_complete_combat_evidence(row)
                    and _asserts_partial_combat_product_outcome(row)
                    and "单项输入不能推导最终分类或展示结果" not in row[8]
                ]
                if unsafe_partial_combat_cases:
                    semantic_errors.append(
                        "a single combat condition cannot imply classification or a displayed "
                        f"result: {unsafe_partial_combat_cases}"
                    )
                unsourced_negative_combat_ui = [
                    row[0]
                    for row in data_rows
                    if _is_combat_case(row)
                    and not _has_complete_combat_evidence(row)
                    and _asserts_unsourced_combat_ui(row)
                ]
                if unsourced_negative_combat_ui:
                    semantic_errors.append(
                        "negative combat cases may use missing source conditions but cannot "
                        "invent a frontend marker, prompt, or classification entry point: "
                        f"{unsourced_negative_combat_ui}"
                    )
                unsourced_positive_combat_ui = [
                    row[0]
                    for row in data_rows
                    if _has_complete_combat_evidence(row)
                    and _asserts_combat_classification(row)
                    and any(
                        term in " ".join((row[7], row[8], row[9]))
                        for term in ("标记", "标识", "标签", "分类入口", "观察活动类型")
                    )
                    and "系统分类入口与结果观察点待确认" not in row[10]
                ]
                if unsourced_positive_combat_ui:
                    semantic_errors.append(
                        "positive combat cases must use the three sourced facts without "
                        "inventing a product classification marker or observation point: "
                        f"{unsourced_positive_combat_ui}"
                    )
            if "内容“真实有效”" in source_corpus and "具体判定方式" in source_corpus:
                content_coverage_requirements = (
                    ("对应圈子", ("对应圈子", "圈子内")),
                    ("活动相关", ("活动相关", "内容相关")),
                    ("活动期", ("活动期",)),
                    ("真实有效", ("真实有效", "灌水", "刷量")),
                )
                if all(
                    any(alias in source_corpus for alias in aliases)
                    for _label, aliases in content_coverage_requirements
                ):
                    missing_content_coverage = [
                        label
                        for label, aliases in content_coverage_requirements
                        if not any(alias in coverage_mapping_text for alias in aliases)
                    ]
                    if missing_content_coverage:
                        semantic_errors.append(
                            "coverage matrix must explicitly map all four sourced content "
                            f"conditions; missing mappings: {missing_content_coverage}"
                        )
                fixed_authenticity_coverage = [
                    row[0]
                    for row in coverage_rows[2:]
                    if len(row) == 3
                    and "内容" in row[0]
                    and any(term in " ".join(row) for term in ("真实有效", "灌水", "刷量"))
                    and any(term in row[2] for term in ("不计", "无效", "过滤"))
                    and "判定机制待确认" not in row[2]
                ]
                if fixed_authenticity_coverage:
                    semantic_errors.append(
                        "content-authenticity coverage must map a blocked case without fixed "
                        f"count outcomes: {fixed_authenticity_coverage}"
                    )
                unsafe_missing_content_coverage = [
                    row[0]
                    for row in coverage_rows[2:]
                    if len(row) == 3
                    and any(term in row[0] for term in ("内容条件", "内容四条件"))
                    and any(term in row[2] for term in ("不计入", "未增加", "保持不变"))
                    and "完整" not in row[2]
                    and "判定机制待确认" not in row[2]
                ]
                if unsafe_missing_content_coverage:
                    semantic_errors.append(
                        "content-condition coverage must map source evidence without assuming a "
                        f"count observation: {unsafe_missing_content_coverage}"
                    )
                incomplete_content_cases = [
                    row[0]
                    for row in data_rows
                    if _asserts_positive_content_count(row)
                    and not _has_content_four_conditions(row)
                ]
                if incomplete_content_cases:
                    semantic_errors.append(
                        "a positive content count requires evidence for all four sourced "
                        f"conditions; incomplete cases: {incomplete_content_cases}"
                    )
                invented_content_judgments = []
                for row in data_rows:
                    result = " ".join((row[8], row[9]))
                    if (
                        _requires_unconfirmed_content_judgment(row)
                        and _asserts_content_count_or_validity(row)
                        and not any(term in result for term in ("不可执行", "阻塞"))
                    ):
                        invented_content_judgments.append(row[0])
                if invented_content_judgments:
                    semantic_errors.append(
                        "content authenticity has no confirmed decision mechanism; do not assert "
                        f"automatic invalidation outcomes: {invented_content_judgments}"
                    )
                unsafe_missing_content_cases = [
                    row[0]
                    for row in data_rows
                    if (
                        "内容条件" in " ".join((row[1], row[2]))
                        or ("#6.3" in row[1] and "条件" in row[1])
                    )
                    and not _has_content_four_conditions(row)
                    and not _requires_unconfirmed_content_judgment(row)
                    and _asserts_content_count_or_validity(row)
                    and "单项条件缺失不足以满足来源中的完整内容定义" not in row[8]
                ]
                if unsafe_missing_content_cases:
                    semantic_errors.append(
                        "a missing content condition proves only that the complete source "
                        "definition is unmet; it does not establish an unconfirmed count UI: "
                        f"{unsafe_missing_content_cases}"
                    )
            if "H5 展示阶段可按当前报名人数做预估" in source_corpus:
                fixed_prestart_estimates = [
                    row[0]
                    for row in data_rows
                    if any(
                        term in " ".join((row[2], row[5], row[6], row[7]))
                        for term in ("未开始", "报名中")
                    )
                    and any(
                        term in " ".join((row[8], row[9]))
                        for term in ("显示", "展示", "文案", "关键词")
                    )
                    and not any(
                        term in " ".join((row[8], row[9], row[10]))
                        for term in ("若采用", "按建议", "展示规则待确认")
                    )
                ]
                if fixed_prestart_estimates:
                    semantic_errors.append(
                        "pre-start estimate display is a source suggestion, not a fixed UI "
                        f"assertion: {fixed_prestart_estimates}"
                    )
                fixed_prestart_coverage = [
                    row[0]
                    for row in coverage_rows[2:]
                    if len(row) == 3
                    and any(term in " ".join(row) for term in ("未开始", "预估", "预计"))
                    and any(term in row[2] for term in ("显示", "展示", "文案", "关键词"))
                    and "展示建议待确认" not in row[2]
                ]
                if fixed_prestart_coverage:
                    semantic_errors.append(
                        "pre-start estimate coverage must remain conditional on the source "
                        f"display suggestion: {fixed_prestart_coverage}"
                    )
            if "前端展示建议" in source_corpus or "可以展示为" in source_corpus:
                fixed_display_suggestions = []
                for row in data_rows:
                    scenario = " ".join((row[2], row[5], row[6], row[7]))
                    result = " ".join((row[8], row[9]))
                    if (
                        "对抗" in scenario
                        and any(term in result for term in ("显示", "展示"))
                        and any(term in result for term in ("胜队", "胜者", "排名"))
                        and not any(
                            term in result
                            for term in ("若采用", "按建议", "待确认", "不可执行", "阻塞")
                        )
                    ):
                        fixed_display_suggestions.append(row[0])
                if fixed_display_suggestions:
                    semantic_errors.append(
                        "suggested combat display copy must not become a fixed UI assertion: "
                        f"{fixed_display_suggestions}"
                    )
                fixed_combat_coverage = [
                    row[0]
                    for row in coverage_rows[2:]
                    if len(row) == 3
                    and "对抗" in row[0]
                    and any(term in row[2] for term in ("展示", "文案"))
                    and "展示建议待确认" not in row[2]
                ]
                if fixed_combat_coverage:
                    semantic_errors.append(
                        "combat coverage must separate sourced classification from suggested "
                        f"display copy: {fixed_combat_coverage}"
                    )
            if "# 推荐样式文案" in source_corpus:
                fixed_card_styles = [
                    row[0]
                    for row in data_rows
                    if (
                        "活动列表卡片" in row[2]
                        or any(
                            term in " ".join((row[8], row[9])) for term in ("立即报名", "底部小字")
                        )
                    )
                    and "推荐样式" not in " ".join((row[8], row[9], row[10]))
                ]
                if fixed_card_styles:
                    semantic_errors.append(
                        "recommended activity-card copy must remain conditional, not a fixed UI "
                        f"assertion: {fixed_card_styles}"
                    )
            formal_config = _formal_reward_config(source_corpus)
            if formal_config:
                unsourced_config_displays = [
                    row[0] for row in data_rows if _has_unsourced_reward_config_display(row)
                ]
                if unsourced_config_displays:
                    semantic_errors.append(
                        "formal new/old-player unit prices are configuration inputs, not a "
                        "confirmed UI display: "
                        f"{unsourced_config_displays}"
                    )
                missing_config_rows = [
                    stage
                    for stage, new_price, old_price, budget_floor, minimum in formal_config
                    if not any(
                        _row_covers_reward_config(
                            row,
                            stage=stage,
                            new_price=new_price,
                            old_price=old_price,
                            budget_floor=budget_floor,
                            minimum=minimum,
                        )
                        for row in data_rows
                    )
                ]
                if missing_config_rows:
                    expected_format = "; ".join(
                        f"第{stage}场:新玩家{new_price}元/老玩家{old_price}元/"
                        f"底标{budget_floor}元/最低核销{minimum}人"
                        for stage, new_price, old_price, budget_floor, minimum in formal_config
                        if stage in missing_config_rows
                    )
                    semantic_errors.append(
                        "formal reward configuration must have exact table-driven coverage for "
                        f"every configured stage; missing stages: {missing_config_rows}; "
                        f"use these exact labeled values in testcase rows: {expected_format}"
                    )
                incompatible_examples = _incompatible_reward_examples(
                    data_rows + coverage_rows[2:], formal_config
                )
                if incompatible_examples:
                    semantic_errors.append(
                        "remove reward unit-price examples that conflict with the formal source "
                        f"configuration: {incompatible_examples}"
                    )
            if "低于预算底标时标记未达成底标" in source_corpus:
                invented_floor_displays = [
                    row[0]
                    for row in data_rows
                    if "底标" in " ".join(row)
                    and "展示位置和文案待确认" not in " ".join((row[8], row[9], row[10]))
                    and "不使用" not in " ".join((row[8], row[9]))
                    and any(
                        term in " ".join((row[8], row[9]))
                        for term in ("页面", "提示", "文案", "显示", "展示")
                    )
                ]
                if invented_floor_displays:
                    semantic_errors.append(
                        "budget-floor state is confirmed but its UI location and copy are not: "
                        f"{invented_floor_displays}"
                    )
            if "成长金发放时机" in source_corpus:
                invented_growth_payouts = [
                    row[0]
                    for row in data_rows
                    if _is_growth_tier_case(row)
                    and (
                        any(
                            term in " ".join((row[8], row[9]))
                            for term in (
                                "到账",
                                "发放记录",
                                "发放一次",
                                "已发放",
                                "展示成长金",
                                "成长金显示",
                                "成长金金额",
                                "成长金为",
                                "成长金记录",
                                "获得成长金",
                                "收到成长金",
                                "不显示",
                                "显示未达标",
                                "显示进度",
                                "无成长金",
                                "可领取",
                                "只显示",
                                "仅显示",
                                "点亮",
                                "激活",
                                "金额为",
                                "界面显示",
                            )
                        )
                        or (
                            bool(re.search(r"\d+\s*元", " ".join((row[8], row[9]))))
                            and any(
                                term in " ".join((row[8], row[9]))
                                for term in ("展示", "截图", "记录", "获得", "金额", "达标")
                            )
                        )
                        or bool(
                            re.search(
                                r"(?:得|最终)\s*\d+\s*元",
                                " ".join((row[8], row[9])),
                            )
                        )
                        or any(
                            term in " ".join((row[5], row[6]))
                            for term in (
                                "已领",
                                "领取",
                                "已获得",
                                "已发放",
                                "到账",
                                "可替换",
                            )
                        )
                        or any(
                            term in row[2] for term in ("领取成长金", "获得成长金", "成长金到账")
                        )
                        or bool(re.search(r"成长金\s*\d+\s*元", row[2]))
                    )
                ]
                if invented_growth_payouts:
                    semantic_errors.append(
                        "growth-fund payout timing is unconfirmed; verify tier selection without "
                        f"asserting到账 evidence: {invented_growth_payouts}"
                    )
                invented_growth_coverage = [
                    row[0]
                    for row in coverage_rows[2:]
                    if len(row) == 3
                    and "成长金" in " ".join(row)
                    and (
                        any(term in row[2] for term in ("发放", "领取", "展示", "只发"))
                        or bool(re.search(r"\d+\s*元", row[2]))
                    )
                    and "展示与发放待确认" not in row[2]
                ]
                if invented_growth_coverage:
                    semantic_errors.append(
                        "growth-fund coverage must map tier selection without fixed display or "
                        f"payout outcomes: {invented_growth_coverage}"
                    )
                unconfirmed_growth_activity_lists = [
                    row[0]
                    for row in data_rows
                    if _is_growth_fund_case(row) and "有效活动列表" in row[6]
                ]
                if unconfirmed_growth_activity_lists:
                    semantic_errors.append(
                        "growth tier inputs may reference source evidence but cannot assume an "
                        f"unconfirmed effective-activity list: {unconfirmed_growth_activity_lists}"
                    )
            if "成长金非个人奖励，仅用于主理人运营的圈子发展使用" in source_corpus:
                growth_copy_payout_preconditions = [
                    row[0]
                    for row in data_rows
                    if "非个人奖励" in " ".join(row)
                    and any(
                        term in " ".join((row[5], row[6])) for term in ("已获得", "已发放", "到账")
                    )
                ]
                if growth_copy_payout_preconditions:
                    semantic_errors.append(
                        "growth-fund explanatory copy must not require an unconfirmed payout "
                        f"fact as its precondition: {growth_copy_payout_preconditions}"
                    )
            if (
                "同一用户在同一圈子内参加多场有效活动，只算 1 人" in source_corpus
                or "同一用户在同一场活动内只能计算一次" in source_corpus
            ):
                unsafe_participant_dedup_observations = [
                    row[0]
                    for row in data_rows
                    if any(
                        term in " ".join((row[1], row[2]))
                        for term in ("玩家人数去重", "玩家统计去重", "只计1人", "计为1名")
                    )
                    and any(
                        term in " ".join((row[7], row[8], row[9]))
                        for term in ("统计", "查询", "展示", "计数")
                    )
                    and "参与玩家统计入口与观察点待确认" not in row[10]
                ]
                if unsafe_participant_dedup_observations:
                    semantic_errors.append(
                        "participant deduplication is source-defined but its product observation "
                        f"point is not: {unsafe_participant_dedup_observations}"
                    )
                if "同一用户在同一圈子内参加多场有效活动，只算 1 人" in source_corpus:
                    dedup_coverage_rows = [
                        coverage_row
                        for coverage_row in coverage_rows[2:]
                        if len(coverage_row) == 3
                        and any(
                            term in " ".join(coverage_row)
                            for term in ("参与玩家去重", "参与玩家统计", "同圈用户去重")
                        )
                    ]
                    mapped_case_ids = {
                        case_id.strip()
                        for coverage_row in dedup_coverage_rows
                        for case_id in re.split(r"[,，、]", coverage_row[1])
                        if case_id.strip()
                    }
                    mapped_dedup_cases = [
                        row[0]
                        for row in data_rows
                        if row[0] in mapped_case_ids and _has_circle_participant_dedup_evidence(row)
                    ]
                    if dedup_coverage_rows and not mapped_dedup_cases:
                        semantic_errors.append(
                            "coverage must map participant deduplication to a testcase with the "
                            "same user, same circle, multiple effective activities, and a "
                            "source-level count-once assertion"
                        )
            untriggerable_growth_rankings = [
                row[0] for row in data_rows if _is_untriggerable_growth_ranking(row, source_corpus)
            ]
            if untriggerable_growth_rankings:
                semantic_errors.append(
                    "unlimited growth-fund configuration cannot execute same-tier overflow "
                    "ranking or mutate the formal configuration: "
                    f"{untriggerable_growth_rankings}"
                )
            reopened_combat_definitions = [
                row[0]
                for row in data_rows
                if _source_has_combat_definition(source_corpus)
                and _has_complete_combat_evidence(row)
                and any(term in row[10] for term in ("非两队形式对抗需明确", "非两队对抗需明确"))
            ]
            if reopened_combat_definitions:
                semantic_errors.append(
                    "team, individual, and ranking combat forms are already source-defined; do "
                    f"not reopen complete cases as pending: {reopened_combat_definitions}"
                )
            if semantic_errors:
                raise ValueError("; ".join(semantic_errors))


__all__ = ["_quality_check"]
