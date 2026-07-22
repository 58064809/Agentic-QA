from __future__ import annotations

import re
from typing import Any

from harness.infrastructure.quality.packs.city_opening_rewards.rules import (
    LOW_PARTICIPANT_PATTERN,
    TESTCASE_HEADERS,
    _append_pending,
    _asserts_combat_classification,
    _asserts_content_count_or_validity,
    _asserts_effective_activity_observation,
    _asserts_partial_combat_product_outcome,
    _asserts_positive_content_count,
    _asserts_positive_reward,
    _asserts_unsourced_combat_ui,
    _expand_coverage_case_id_range,
    _explicit_new_old_player_count,
    _formal_reward_config,
    _has_complete_combat_evidence,
    _has_content_four_conditions,
    _has_reward_six_conditions,
    _has_unsourced_reward_config_display,
    _incompatible_reward_examples,
    _is_combat_case,
    _is_coverage_header,
    _is_growth_fund_case,
    _is_growth_tier_case,
    _is_missing_combat_condition_case,
    _is_missing_reward_condition_case,
    _is_no_growth_tier_case,
    _is_reward_condition_case,
    _is_untriggerable_growth_ranking,
    _markdown_cells,
    _replace_unsupported_terms,
    _requires_unconfirmed_content_judgment,
    _row_covers_reward_config,
    _source_backed_reward_config_row,
    _source_has_combat_definition,
    _source_has_distinct_activity_scopes,
    _unsupported_implementation_terms,
)


def _deterministically_enrich_artifact(
    artifact: str,
    content: str,
    *,
    source_corpus: str,
) -> tuple[str, dict[str, Any] | None]:
    if artifact != "testcases":
        return content, None
    lines = content.splitlines()
    rows = [_markdown_cells(line) for line in lines]
    header_index = next(
        (index for index, cells in enumerate(rows) if cells == list(TESTCASE_HEADERS)),
        None,
    )
    coverage_index = next(
        (
            index
            for index, line in enumerate(lines)
            if header_index is not None
            and index > header_index
            and line.lstrip().startswith("#")
            and "覆盖矩阵" in line
        ),
        None,
    )
    if header_index is None or coverage_index is None:
        return content, None
    rules: list[str] = []
    normalized_case_ids: list[str] = []
    normalized_source = source_corpus.replace(" ", "")
    formal_config = _formal_reward_config(source_corpus)
    for index in range(header_index + 2, coverage_index):
        row = _markdown_cells(lines[index])
        if len(row) != len(TESTCASE_HEADERS):
            continue
        changed = False
        scenario = " ".join((row[2], row[5], row[6], row[7]))
        result = " ".join((row[8], row[9]))
        unsupported_terms = _unsupported_implementation_terms(" ".join(row), source_corpus)
        if unsupported_terms:
            original = list(row)
            row = [_replace_unsupported_terms(cell, unsupported_terms) for cell in row]
            for field, prefix in (
                (5, "若相关产品入口经确认："),
                (7, "若相关产品入口经确认："),
                (8, "若相关产品行为经确认："),
                (9, "仅在观察点经确认后采集："),
            ):
                if any(term in original[field] for term in unsupported_terms):
                    row[field] = prefix + row[field]
            row[10] = _append_pending(row[10], "具体产品入口与观察点待确认")
            rules.append("condition_unsourced_implementation_observation")
            changed = True
            scenario = " ".join((row[2], row[5], row[6], row[7]))
            result = " ".join((row[8], row[9]))
        if (
            "领取奖励条件" in source_corpus
            and _is_reward_condition_case(row)
            and not _has_reward_six_conditions(row)
            and not any(
                term in row[8]
                for term in (
                    "不单独推导最终奖励资格",
                    "不满足来源中要求同时成立的全部领取条件",
                )
            )
        ):
            if _is_missing_reward_condition_case(row):
                row[2] = "核对缺失单项领取条件（具体处理待确认）"
                row[7] = "核对该用例中缺失的来源条件；具体产品处理入口待确认"
                row[8] = "不满足来源中要求同时成立的全部领取条件；具体产品处理待确认"
            else:
                row[2] = "核对单项领取条件输入（最终资格待完整核对）"
                row[7] = "核对当前来源条件的输入证据；最终资格仍需完整核对六项条件"
                row[8] = "仅确认当前来源条件满足；不单独推导最终奖励资格或处理结果"
            row[9] = "保留当前条件的输入证据，不断言未定义界面、提示或发放记录"
            row[10] = _append_pending(row[10], "六项领取条件的完整证据与处理入口待确认")
            rules.append("condition_partial_reward_evidence")
            changed = True
            scenario = " ".join((row[2], row[5], row[6], row[7]))
            result = " ".join((row[8], row[9]))
        if (
            "领取奖励条件" in source_corpus
            and _is_reward_condition_case(row)
            and not _has_reward_six_conditions(row)
        ):
            missing_condition = _is_missing_reward_condition_case(row)
            desired_title = (
                "核对缺失单项领取条件（具体处理待确认）"
                if missing_condition
                else "核对单项领取条件输入（最终资格待完整核对）"
            )
            if desired_title not in row[2]:
                row[2] = desired_title
                rules.append("align_partial_reward_case_title")
                changed = True
            if missing_condition and "不满足来源中要求同时成立的全部领取条件" not in row[8]:
                row[7] = "核对该用例中缺失的来源条件；具体产品处理入口待确认"
                row[8] = "不满足来源中要求同时成立的全部领取条件；具体产品处理待确认"
                row[9] = "保留当前条件的输入证据，不断言未定义界面、提示或发放记录"
                row[10] = _append_pending(row[10], "六项领取条件的完整证据与处理入口待确认")
                rules.append("restore_missing_reward_condition_semantics")
                changed = True
        if (
            "领取奖励条件" in source_corpus
            and _is_reward_condition_case(row)
            and "不断言未定义界面、提示或发放记录" not in result
            and any(
                term in result
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
        ):
            if _is_missing_reward_condition_case(row):
                row[7] = "核对该用例中缺失的来源条件；具体产品处理入口待确认"
                row[8] = "不满足来源中要求同时成立的全部领取条件；具体产品处理待确认"
            else:
                row[2] = "核对六项领取条件输入（奖励处理待确认）"
                row[7] = (
                    "核对报名、核销、获奖名单、趣看动态、#今天一起开局话题和"
                    "@交子立方官方号六项输入证据；具体产品处理入口待确认"
                )
                row[8] = "满足来源中的六项领取条件；具体奖励处理与时机待确认"
            row[9] = "保留六项条件的输入证据，不断言未定义界面、提示或发放记录"
            row[10] = _append_pending(row[10], "奖励处理入口、时机与观察点待确认")
            rules.append("remove_unsourced_reward_condition_observation")
            changed = True
            scenario = " ".join((row[2], row[5], row[6], row[7]))
            result = " ".join((row[8], row[9]))
        if (
            _source_has_distinct_activity_scopes(source_corpus)
            and "有效活动" in " ".join(row)
            and any(term in row[10] for term in ("是否统一", "是否合并", "口径统一"))
        ):
            row[10] = "奖励场次四条件与成长金三条件分别按来源执行"
            rules.append("preserve_distinct_activity_scopes")
            changed = True
        if (
            _source_has_distinct_activity_scopes(source_corpus)
            and _asserts_effective_activity_observation(row)
            and "产品标记、计数入口与观察点待确认" not in row[10]
            and "奖励场次四条件与成长金三条件分别按来源执行" not in row[10]
        ):
            row[7] = "按来源分别核对奖励四条件与成长金三条件的输入证据"
            row[8] = "仅依据来源判定该组输入满足对应有效活动定义；不推导未确认产品展示"
            row[9] = "保存 App 发布、报名人数、活动完成及适用时的核销证据"
            row[10] = _append_pending(row[10], "产品标记、计数入口与观察点待确认")
            rules.append("condition_effective_activity_observation")
            changed = True
        if "最低核销人数" in source_corpus and "10人" in source_corpus:
            non_executable = " ".join((row[2], row[7], row[8], row[10]))
            low_participant_case = bool(LOW_PARTICIPANT_PATTERN.search(scenario)) or (
                "低于最低核销人数" in scenario
                or ("核销" in scenario and any(term in scenario for term in ("低于10", "<10")))
            )
            if (
                low_participant_case
                and row[7].strip() in {"-", "无", "不执行"}
                and "来源最低核销人数为10人" not in row[5]
            ):
                row[5] = "来源最低核销人数为10人；当前样例低于正式门槛"
                row[6] = "仅保留低人数作为数学说明，不构造可执行奖励场景"
                rules.append("normalize_low_participant_note")
                changed = True
            if (
                low_participant_case
                and row[7].strip() in {"-", "无", "不执行", "N/A"}
                and any(
                    term in " ".join((row[8], row[9]))
                    for term in ("显示", "提示", "不计入", "不触发", "奖励结果")
                )
            ):
                row[7] = "不执行"
                row[8] = "不可执行：仅确认低于最低核销人数，后续产品行为待确认"
                row[9] = "来源配置中的最低核销人数；不产生产品结果断言"
                row[10] = _append_pending(row[10], "低于门槛后的资格、提示与奖励处理待确认")
                rules.append("remove_low_participant_product_outcome")
                changed = True
            if low_participant_case and not (
                any(term in non_executable for term in ("不可执行", "不执行", "仅作数学说明"))
                and row[7].strip() in {"-", "无", "不执行"}
            ):
                row[5] = "来源最低核销人数为10人；当前样例低于正式门槛"
                row[6] = "仅保留低人数作为数学说明，不构造可执行奖励场景"
                row[7] = "不执行"
                row[8] = "不可执行：仅确认低于最低核销人数，后续产品行为待确认"
                row[9] = "来源配置中的最低核销人数；不产生产品结果断言"
                row[10] = _append_pending(row[10], "低于门槛后的资格、提示与奖励处理待确认")
                rules.append("block_low_participant_case")
                changed = True
        if "约50%" in normalized_source and "开发计算建议" in normalized_source:
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
            if uses_suggestion and "按来源约50%建议核对" not in row[2]:
                row[2] = f"按来源约50%建议核对：{row[2]}"
                if row[7].strip() not in {"-", "无", "不执行"}:
                    row[7] = f"若采用来源当前建议：{row[7]}"
                row[10] = _append_pending(row[10], "获奖比例及取整规则待确认")
                rules.append("condition_approximate_suggestion")
                changed = True
            if uses_suggestion and asserts_fixed_result:
                row[8] = f"若采用来源中的当前建议：{row[8]}；最终比例及取整规则待确认"
                row[9] = "仅记录按建议推导的结果，不作为已确认产品断言"
                row[10] = _append_pending(row[10], "获奖比例及取整规则待确认")
                rules.append("condition_approximate_suggestion")
                changed = True
        if (
            "H5 展示阶段可按当前报名人数做预估" in source_corpus
            and any(term in scenario for term in ("未开始", "报名中"))
            and any(term in result for term in ("显示", "展示", "文案", "关键词"))
            and not any(term in result for term in ("若采用", "按建议", "待确认"))
        ):
            row[7] = "若采用来源中的预估展示建议，核对未开始活动的预估信息"
            row[8] = "若采用来源建议，预估信息使用“预计”口径；最终展示规则待确认"
            row[9] = "仅记录来源建议的条件式对照，不作为已确认固定界面断言"
            row[10] = _append_pending(row[10], "预估展示位置、文案与计算规则待确认")
            rules.append("condition_prestart_estimate_display")
            changed = True
        if "内容“真实有效”" in source_corpus and "具体判定方式" in source_corpus:
            if _asserts_positive_content_count(row) and not _has_content_four_conditions(row):
                row[7] = "仅核对当前内容条件；完整有效性与计数需同时满足来源四条件"
                row[8] = "当前单项条件通过不代表内容可计数；完整结果待四条件共同核对"
                row[9] = "保存当前条件证据，不产生内容有效性或计数断言"
                row[10] = _append_pending(row[10], "内容四条件的完整证据待补齐")
                rules.append("condition_incomplete_content_eligibility")
                changed = True
                scenario = " ".join((row[2], row[5], row[6], row[7]))
                result = " ".join((row[8], row[9]))
            if (
                _requires_unconfirmed_content_judgment(row)
                and _asserts_content_count_or_validity(row)
                and not any(term in result for term in ("不可执行", "阻塞"))
            ):
                row[7] = "不执行"
                row[8] = "阻塞：内容真实性判定方式未确认，不产生计数或有效性结果断言"
                row[9] = "来源仅确认真实性原则，缺少判定机制证据"
                row[10] = _append_pending(row[10], "内容真实性判定方式待确认")
                rules.append("block_unconfirmed_content_judgment")
                changed = True
            if (
                (
                    "内容条件" in " ".join((row[1], row[2]))
                    or ("#6.3" in row[1] and "条件" in row[1])
                )
                and not _has_content_four_conditions(row)
                and not _requires_unconfirmed_content_judgment(row)
                and _asserts_content_count_or_validity(row)
                and "单项条件缺失不足以满足来源中的完整内容定义" not in row[8]
            ):
                row[2] = "核对缺失的单项内容条件（计数观察点待确认）"
                row[7] = "核对当前缺失条件的输入证据；不依赖未确认的内容计数入口"
                row[8] = "单项条件缺失不足以满足来源中的完整内容定义"
                row[9] = "保存缺失条件证据，不断言未定义的内容计数界面或数值变化"
                row[10] = _append_pending(row[10], "内容计数入口与观察点待确认")
                rules.append("condition_missing_content_evidence")
                changed = True
        if (
            "活动期的起止时间或重置规则" in source_corpus
            and "活动期" in " ".join(row)
            and re.search(r"20\d{2}-\d{2}-\d{2}", " ".join(row))
        ):
            row[5] = "已取得活动期规则来源；具体起止时间尚未确认"
            row[6] = "活动期内与活动期外的来源证据（具体日期待确认）"
            row[7] = "待活动期起止时间确认后，核对内容发布时间是否位于活动期内"
            row[8] = "仅按已确认活动期边界核对；当前不使用示例日期作固定断言"
            row[9] = "活动期配置与内容发布时间证据"
            row[10] = _append_pending(row[10], "活动期的起止时间或重置规则待确认")
            rules.append("remove_invented_activity_period_dates")
            changed = True
        if (
            _source_has_combat_definition(source_corpus)
            and _is_missing_combat_condition_case(row)
            and "缺少任一来源条件时，不按来源定义归类为对抗类" not in row[8]
        ):
            row[2] = "核对缺失的对抗类来源条件（产品标识待确认）"
            row[7] = "核对该活动明确缺失的对抗关系、胜负或排名规则、结束结果之一"
            row[8] = "缺少任一来源条件时，不按来源定义归类为对抗类"
            row[9] = "保存缺失条件证据，不断言未定义的前端标识、提示或分类入口"
            row[10] = _append_pending(row[10], "产品分类入口与展示方式待确认")
            rules.append("condition_missing_combat_evidence")
            changed = True
        if (
            _source_has_combat_definition(source_corpus)
            and _has_complete_combat_evidence(row)
            and _asserts_combat_classification(row)
            and any(
                term in " ".join((row[7], row[8], row[9]))
                for term in ("标记", "标识", "标签", "分类入口", "观察活动类型")
            )
        ):
            row[7] = "核对同一活动的对抗关系、胜负或排名规则，以及活动结束后的可确认结果"
            row[8] = "同一活动同时满足三个来源条件，可按来源定义归类为对抗类"
            row[9] = "保存玩法规则、胜负或排名规则和活动结果三类证据"
            row[10] = _append_pending(row[10], "系统分类入口与结果观察点待确认")
            rules.append("remove_unsourced_combat_classification_ui")
            changed = True
        if "前端展示建议" in source_corpus or "可以展示为" in source_corpus:
            if (
                "对抗" in scenario
                and (
                    not _source_has_combat_definition(source_corpus)
                    or _has_complete_combat_evidence(row)
                )
                and any(term in result for term in ("显示", "展示"))
                and any(term in result for term in ("胜队", "胜者", "排名"))
                and not any(
                    term in result for term in ("若采用", "按建议", "待确认", "不可执行", "阻塞")
                )
            ):
                row[7] = "核对同一活动的对抗关系、胜负或排名规则及结束结果"
                if _source_has_combat_definition(source_corpus):
                    row[2] = "按来源三条件核对对抗类分类（展示待确认）"
                    row[8] = "同一活动同时满足来源三条件时，按来源定义归类为对抗类"
                    row[9] = "保存同一活动的对抗关系、胜负或排名规则和结束结果三类证据"
                else:
                    row[8] = "来源中的对抗类展示仅为建议；最终展示规则待确认"
                    row[9] = "仅核对展示建议，不作为已确认固定界面断言"
                row[10] = _append_pending(row[10], "对抗类展示规则待确认")
                rules.append("condition_combat_display_suggestion")
                changed = True
        if (
            "成长金发放时机" in source_corpus
            and _is_growth_tier_case(row)
            and "当前不限名额配置不会触发" not in row[8]
        ):
            growth_result = " ".join((row[8], row[9]))
            unconfirmed_growth_precondition = any(
                term in " ".join((row[5], row[6]))
                for term in ("已领", "领取", "已获得", "已发放", "到账", "可替换")
            )
            unconfirmed_growth_description = any(
                term in row[2] for term in ("领取成长金", "获得成长金", "成长金到账")
            ) or bool(re.search(r"成长金\s*\d+\s*元", row[2]))
            unconfirmed_growth_result = "不使用发放结果作为证据" not in growth_result and (
                any(
                    term in growth_result
                    for term in (
                        "到账",
                        "发放",
                        "前端显示",
                        "展示成长金",
                        "成长金显示",
                        "成长金金额",
                        "成长金为",
                        "领取记录",
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
                    bool(re.search(r"\d+\s*元", growth_result))
                    and any(
                        term in growth_result
                        for term in ("展示", "截图", "记录", "获得", "金额", "达标")
                    )
                )
                or bool(re.search(r"(?:得|最终)\s*\d+\s*元", growth_result))
            )
            if (
                unconfirmed_growth_result
                or unconfirmed_growth_precondition
                or unconfirmed_growth_description
            ):
                if _is_no_growth_tier_case(row):
                    row[2] = "核对未满足任何成长金档位（发放与展示待确认）"
                    row[8] = "仅核对未满足任何已确认成长金档位；发放与展示行为待确认"
                else:
                    row[2] = "核对满足条件时选择的最高成长金档位（发放待确认）"
                    row[8] = "仅核对满足条件时选择的最高成长金档位；实际发放时机待确认"
                row[9] = "来源中的档位和不叠加规则，不使用发放结果作为证据"
                row[7] = "核对来源门槛与满足条件时的最高档位选择"
                if unconfirmed_growth_precondition:
                    row[5] = "已取得圈子的有效活动、去重参与玩家和内容数量来源证据"
                row[10] = _append_pending(row[10], "成长金发放时机待确认")
                rules.append("remove_unconfirmed_growth_payout")
                changed = True
        if (
            "成长金非个人奖励，仅用于主理人运营的圈子发展使用" in source_corpus
            and "非个人奖励" in " ".join(row)
            and any(term in " ".join((row[5], row[6])) for term in ("已获得", "已发放", "到账"))
        ):
            row[5] = "可访问来源定义的成长金说明内容"
            row[6] = "来源中的成长金用途说明文案"
            row[7] = "核对来源明确的成长金非个人奖励说明"
            row[8] = "文案表达成长金非个人奖励，仅用于主理人运营的圈子发展"
            row[9] = "来源文案与候选内容的对照结果；不使用发放结果作为证据"
            row[10] = _append_pending(row[10], "具体展示位置与最终视觉样式待确认")
            rules.append("remove_growth_copy_payout_precondition")
            changed = True
        if _is_untriggerable_growth_ranking(row, source_corpus):
            row[2] = "记录同档超额排序规则（当前配置不可触发）"
            row[5] = "当前三个成长金档位均不限名额"
            row[6] = "来源中的同档超额排序规则"
            row[7] = "不执行"
            row[8] = "不可执行：当前不限名额配置不会触发同档超额排序"
            row[9] = "仅保留来源规则映射，不修改当前正式配置，不产生发放结果"
            row[10] = "若未来正式名额配置变为有限，再依据届时配置设计可执行用例"
            rules.append("block_untriggerable_growth_ranking")
            changed = True
        if (
            "领取奖励条件" in source_corpus
            and _asserts_positive_reward(row)
            and not _has_reward_six_conditions(row)
        ):
            row[8] = (
                "仅确认当前活动结果可作为获奖依据；最终奖励资格待确认，仍需同时核对六项领取条件"
            )
            row[9] = "活动结果证据与六项领取条件核对记录"
            row[10] = _append_pending(row[10], "六项领取条件的完整证据待补齐")
            rules.append("condition_incomplete_reward_eligibility")
            changed = True
        if (
            _source_has_combat_definition(source_corpus)
            and _is_combat_case(row)
            and "奖励" in " ".join((row[8], row[9]))
            and "若采用来源中的展示建议" not in row[8]
        ):
            if _asserts_combat_classification(row):
                row[8] = "同一活动同时满足来源三条件时，按来源定义归类为对抗类"
            elif _has_complete_combat_evidence(row):
                row[8] = "同一活动同时满足来源三条件时，按来源定义归类为对抗类"
            else:
                row[8] = "缺少任一来源条件时，不按对抗类定义归类"
            row[9] = "仅保存同一活动的对抗关系、胜负或排名规则、结束结果三类证据"
            rules.append("remove_combat_reward_observation")
            changed = True
        if (
            _source_has_combat_definition(source_corpus)
            and _asserts_combat_classification(row)
            and not _has_complete_combat_evidence(row)
        ):
            row[7] = "不执行"
            row[8] = "不可执行：单个条件不足以判定对抗类，必须同时证明来源中的三个条件"
            row[9] = "来源中的对抗关系、胜负或排名规则、结束后可确认结果三项定义"
            row[10] = _append_pending(row[10], "三项条件的活动证据待补齐")
            rules.append("block_incomplete_combat_classification")
            changed = True
        if (
            _source_has_combat_definition(source_corpus)
            and _has_complete_combat_evidence(row)
            and "来源中的对抗类展示仅为建议" in row[8]
        ):
            row[2] = "按来源三条件核对对抗类分类（展示待确认）"
            row[8] = "同一活动同时满足来源三条件时，按来源定义归类为对抗类"
            row[9] = "保存同一活动的对抗关系、胜负或排名规则和结束结果三类证据"
            row[10] = _append_pending(row[10], "对抗类展示规则待确认")
            rules.append("restore_source_backed_combat_classification")
            changed = True
        if (
            _source_has_combat_definition(source_corpus)
            and _has_complete_combat_evidence(row)
            and any(
                term in row[8]
                for term in (
                    "不按对抗类",
                    "不归类为对抗类",
                    "非对抗类",
                    "不满足对抗类定义",
                )
            )
        ):
            row[8] = "同一活动同时满足来源三条件时，按来源定义归类为对抗类"
            row[9] = "保存同一活动的对抗关系、胜负或排名规则和结束结果三类证据"
            rules.append("correct_complete_combat_classification")
            changed = True
        if (
            _source_has_combat_definition(source_corpus)
            and _is_combat_case(row)
            and not _has_complete_combat_evidence(row)
            and _asserts_partial_combat_product_outcome(row)
            and "单项输入不能推导最终分类或展示结果" not in row[8]
        ):
            row[2] = "核对单项对抗类条件输入（最终分类待三项完整核对）"
            row[7] = "核对当前来源条件的输入证据；不单独判定对抗类"
            row[8] = "仅确认当前条件输入；单项输入不能推导最终分类或展示结果"
            row[9] = "保留当前条件证据，不断言未定义的系统胜负展示或分类入口"
            row[10] = _append_pending(row[10], "同一活动三项条件的完整证据待补齐")
            rules.append("condition_partial_combat_evidence")
            changed = True
        if (
            _source_has_combat_definition(source_corpus)
            and _is_combat_case(row)
            and not _has_complete_combat_evidence(row)
            and _asserts_unsourced_combat_ui(row)
        ):
            row[2] = "核对缺失的对抗类来源条件（产品标识待确认）"
            row[7] = "核对该活动缺失的对抗关系、胜负或排名规则、结束结果之一"
            row[8] = "缺少任一来源条件时，不按来源定义归类为对抗类"
            row[9] = "保存缺失条件证据，不断言未定义的前端标识、提示或分类入口"
            row[10] = _append_pending(row[10], "产品分类入口与展示方式待确认")
            rules.append("remove_unsourced_combat_ui")
            changed = True
        if (
            "低于预算底标时标记未达成底标" in source_corpus
            and "底标" in " ".join(row)
            and any(term in result for term in ("页面", "提示", "文案", "显示", "展示"))
            and "展示位置和文案待确认" not in " ".join((row[8], row[9], row[10]))
            and "不使用" not in result
        ):
            row[2] = "核对低于正式预算底标时的未达成状态（展示待确认）"
            row[7] = "按正式配置和实际人数计算奖金池，并与对应预算底标核对"
            row[8] = "低于正式预算底标时标记为未达成底标；展示位置和文案待确认"
            row[9] = "正式配置快照、人数输入、计算过程和未达成状态证据"
            row[10] = "未达成底标的展示位置、文案与观察点待确认"
            rules.append("remove_unsourced_budget_floor_display")
            changed = True
        if (
            "成长金发放时机" in source_corpus
            and _is_growth_fund_case(row)
            and "有效活动列表" in row[6]
        ):
            row[6] = row[6].replace("有效活动列表", "有效活动来源证据")
            rules.append("remove_unconfirmed_growth_activity_list")
            changed = True
        if (
            (
                "同一用户在同一圈子内参加多场有效活动，只算 1 人" in source_corpus
                or "同一用户在同一场活动内只能计算一次" in source_corpus
            )
            and any(
                term in " ".join((row[1], row[2]))
                for term in (
                    "玩家人数去重",
                    "玩家统计去重",
                    "参与玩家去重",
                    "只计1人",
                    "仅计为1人",
                    "计为1名",
                    "只算1人",
                    "只计算1人",
                )
            )
            and "不依赖未确认展示入口" not in row[9]
        ):
            dedup_scenario = " ".join((row[1], row[2], row[5], row[6]))
            if any(term in dedup_scenario for term in ("同一活动", "同一场活动")):
                row[7] = "核对同一用户和同一场活动内的报名、核销来源输入证据"
                row[8] = "按来源规则，同一用户在同一场活动内只计算一次"
                row[9] = "用户标识、活动标识及有效参与证据；不依赖未确认展示入口"
            else:
                row[7] = "核对同一用户、同一圈子和多场有效活动的来源输入证据"
                row[8] = "按来源规则，该用户在同一圈子的参与玩家统计中只计 1 人"
                row[9] = "用户标识、圈子标识及各场有效参与证据；不依赖未确认展示入口"
            row[10] = _append_pending(row[10], "参与玩家统计入口与观察点待确认")
            rules.append("condition_participant_dedup_observation")
            changed = True
        if formal_config:
            if "第11场" in " ".join(row) and "成长金" in row[1] and "奖金池" in " ".join(row):
                row[1] = "奖励场次第10场以后沿用正式配置"
                row[2] = "第11场沿用第10场正式奖励配置"
                rules.append("correct_post_max_stage_scope")
                changed = True
            participant_count = _explicit_new_old_player_count(row)
            if participant_count is not None and participant_count < min(
                item[4] for item in formal_config
            ):
                row[7] = "不执行"
                row[8] = "不可执行：明确的新老玩家合计低于最低核销人数"
                row[9] = "来源配置中的最低核销人数；不产生奖金池或奖励结果断言"
                row[10] = _append_pending(row[10], "低于门槛后的奖励处理待确认")
                rules.append("block_low_new_old_player_example")
                changed = True
            conflicting_reward = bool(_incompatible_reward_examples([row], formal_config))
            unsourced_config_display = _has_unsourced_reward_config_display(row)
            if conflicting_reward or unsourced_config_display:
                row = _source_backed_reward_config_row(row)
                rules.append(
                    "remove_conflicting_reward_example"
                    if conflicting_reward
                    else "remove_unsourced_reward_config_display"
                )
                changed = True
        if "# 推荐样式文案" in source_corpus and (
            "活动列表卡片" in row[2]
            or any(term in " ".join((row[8], row[9])) for term in ("立即报名", "底部小字"))
        ):
            row[7] = "若采用来源中的推荐样式，核对活动卡片元素"
            row[8] = "来源中的活动名称、场次、地点、时间、预计金额、按钮及底部说明均为推荐样式"
            row[9] = "仅记录推荐样式对照结果，不作为已确认固定界面断言"
            row[10] = _append_pending(row[10], "活动卡片最终样式与文案待确认")
            rules.append("condition_recommended_card_style")
            changed = True
        if (
            _source_has_combat_definition(source_corpus)
            and _has_complete_combat_evidence(row)
            and any(term in row[10] for term in ("非两队形式对抗需明确", "非两队对抗需明确"))
        ):
            row[10] = (
                row[10].replace("非两队形式对抗需明确规范；", "").replace("非两队对抗需明确；", "")
            )
            row[10] = row[10].strip("； ") or "无"
            rules.append("remove_reopened_combat_definition")
            changed = True
        if changed:
            lines[index] = "| " + " | ".join(row) + " |"
            normalized_case_ids.append(row[0])

    for index in range(coverage_index + 1, len(lines)):
        row = _markdown_cells(lines[index])
        if len(row) != 3:
            continue
        original_coverage_row = list(row)
        expanded_case_ids = _expand_coverage_case_id_range(row[1])
        if expanded_case_ids != row[1]:
            row[1] = expanded_case_ids
            rules.append("expand_coverage_case_id_range")
        unsupported_terms = _unsupported_implementation_terms(" ".join(row), source_corpus)
        if unsupported_terms:
            row = [_replace_unsupported_terms(cell, unsupported_terms) for cell in row]
            row[2] += "；具体产品入口与观察点待确认"
            lines[index] = "| " + " | ".join(row) + " |"
            rules.append("condition_unsourced_implementation_coverage")
            normalized_case_ids.append(row[1])
        if (
            "成长金发放时机" in source_corpus
            and "成长金" in " ".join(row)
            and (
                any(term in row[2] for term in ("发放", "领取", "展示", "只发"))
                or bool(re.search(r"\d+\s*元", row[2]))
            )
            and "展示与发放待确认" not in row[2]
        ):
            if any(term in " ".join(row) for term in ("不足", "未达", "无成长金")):
                row[2] = "核对未达到对应成长金档位；展示与发放待确认"
            else:
                row[2] = "核对满足条件时只选择最高成长金档位；展示与发放待确认"
            lines[index] = "| " + " | ".join(row) + " |"
            rules.append("condition_growth_payout_coverage")
            normalized_case_ids.append(row[1])
        if (
            "领取奖励条件" in source_corpus
            and "奖励" in row[0]
            and any(term in row[2] for term in ("发放", "到账", "领取奖励", "领取成功"))
            and "处理与时机待确认" not in row[2]
        ):
            row[2] = "核对六项领取条件映射；奖励处理与时机待确认"
            lines[index] = "| " + " | ".join(row) + " |"
            rules.append("condition_reward_payout_coverage")
            normalized_case_ids.append(row[1])
        if (
            "H5 展示阶段可按当前报名人数做预估" in source_corpus
            and any(term in " ".join(row) for term in ("未开始", "预估", "预计"))
            and any(term in row[2] for term in ("显示", "展示", "文案", "关键词"))
            and "展示建议待确认" not in row[2]
        ):
            row[2] = "若采用来源中的预估展示建议，使用“预计”口径；展示建议待确认"
            lines[index] = "| " + " | ".join(row) + " |"
            rules.append("condition_prestart_estimate_coverage")
            normalized_case_ids.append(row[1])
        if (
            "内容“真实有效”" in source_corpus
            and "具体判定方式" in source_corpus
            and "内容" in row[0]
            and any(term in " ".join(row) for term in ("真实有效", "灌水", "刷量"))
            and any(term in row[2] for term in ("不计", "无效", "过滤"))
            and "判定机制待确认" not in row[2]
        ):
            row[2] = "真实性判定机制待确认；仅映射阻塞用例，不断言内容计数结果"
            lines[index] = "| " + " | ".join(row) + " |"
            rules.append("condition_content_authenticity_coverage")
            normalized_case_ids.append(row[1])
        if (
            ("前端展示建议" in source_corpus or "可以展示为" in source_corpus)
            and "对抗" in row[0]
            and any(term in row[2] for term in ("展示", "文案"))
            and "展示建议待确认" not in row[2]
        ):
            row[2] = "按来源三条件核对对抗类分类；展示建议待确认"
            lines[index] = "| " + " | ".join(row) + " |"
            rules.append("condition_combat_display_coverage")
            normalized_case_ids.append(row[1])
        if formal_config and _incompatible_reward_examples([row], formal_config):
            row[0] = "正式奖励配置与计算（已移除冲突示意值）"
            row[2] = "以 TC-CONFIG-SOURCE 的正式来源表和来源计算公式为准"
            lines[index] = "| " + " | ".join(row) + " |"
            rules.append("remove_conflicting_reward_coverage")
            normalized_case_ids.append(row[1])
        if (
            "领取奖励条件" in source_corpus
            and any(term in row[0] for term in ("奖励条件", "奖励领取六条件"))
            and row[2] != "核对当前来源条件输入；最终资格需同时满足六项领取条件"
        ):
            row[2] = "核对当前来源条件输入；最终资格需同时满足六项领取条件"
            rules.append("condition_partial_reward_coverage")
        if any(term in row[0] for term in ("内容条件", "内容四条件")) and row[2] not in {
            "真实性判定机制待确认；仅映射阻塞用例，不断言内容计数结果",
            "核对当前来源条件输入；内容计数需同时满足四项条件",
        }:
            if any(term in row[0] for term in ("真实有效", "灌水", "刷量")):
                row[2] = "真实性判定机制待确认；仅映射阻塞用例，不断言内容计数结果"
            else:
                row[2] = "核对当前来源条件输入；内容计数需同时满足四项条件"
            rules.append("condition_content_coverage")
        if (
            _source_has_combat_definition(source_corpus)
            and "对抗类条件" in row[0]
            and row[2] != "仅映射单项条件输入；最终分类需同一活动三项证据完整"
        ):
            row[2] = "仅映射单项条件输入；最终分类需同一活动三项证据完整"
            rules.append("condition_partial_combat_coverage")
        if "第11场" in row[0] and formal_config and row[2] != "第10场及以后沿用正式第10场配置":
            row[2] = "第10场及以后沿用正式第10场配置"
            rules.append("condition_post_max_stage_coverage")
        if (
            "当前均不限名额" in source_corpus
            and "名额不限" in row[0]
            and row[2] != "核对每个圈子的档位选择；当前不限名额，不断言竞争排序或发放结果"
        ):
            row[2] = "核对每个圈子的档位选择；当前不限名额，不断言竞争排序或发放结果"
            rules.append("condition_unlimited_tier_coverage")
        if (
            _source_has_distinct_activity_scopes(source_corpus)
            and "有效活动" in row[0]
            and row[2] != "按来源核对对应条件输入；产品标记、计数入口与观察点待确认"
        ):
            row[2] = "按来源核对对应条件输入；产品标记、计数入口与观察点待确认"
            rules.append("condition_effective_activity_coverage")
        if (
            "成长金发放时机" in source_corpus
            and any(term in row[0] for term in ("成长金第一档", "成长金第二档", "成长金第三档"))
            and row[2] != "核对来源门槛与最高满足档位；不映射产品结果"
        ):
            row[2] = "核对来源门槛与最高满足档位；不映射产品结果"
            rules.append("condition_growth_tier_coverage")
        if (
            _source_has_combat_definition(source_corpus)
            and "对抗类" in row[0]
            and any(term in row[0] for term in ("缺少", "无法确认"))
            and row[2] != "按缺失的来源条件核对负向分类；产品标识待确认"
        ):
            row[2] = "按缺失的来源条件核对负向分类；产品标识待确认"
            rules.append("condition_negative_combat_coverage")
        if formal_config and "奖金池计算与人均" in row[0]:
            row[0] = "正式奖励配置与来源计算公式"
            row[1] = "TC-CONFIG-SOURCE"
            row[2] = "核对正式逐场配置与来源公式；比例和取整建议另作条件式核对"
            rules.append("align_reward_calculation_coverage")
        if (
            formal_config
            and "第10场以后" in row[0]
            and (row[1] != "TC-CONFIG-SOURCE" or row[2] != "正式来源确认第10场及以后沿用第10场配置")
        ):
            row[1] = "TC-CONFIG-SOURCE"
            row[2] = "正式来源确认第10场及以后沿用第10场配置"
            rules.append("align_post_max_stage_coverage")
        if (
            "同一用户在同一圈子内参加多场有效活动，只算 1 人" in source_corpus
            and "玩家去重" in row[0]
            and row[2] != "按来源核对同圈用户去重规则；统计入口与观察点待确认"
        ):
            row[2] = "按来源核对同圈用户去重规则；统计入口与观察点待确认"
            rules.append("condition_participant_dedup_coverage")
        if (
            formal_config
            and ("场次单价映射" in row[0] or "主理人场次规则与单价映射" in row[0])
            and (
                row[1] != "TC-CONFIG-SOURCE"
                or row[2] != "由正式来源表核对全部场次字段及第10场以后沿用规则"
            )
        ):
            row[1] = "TC-CONFIG-SOURCE"
            row[2] = "由正式来源表核对全部场次字段及第10场以后沿用规则"
            rules.append("align_formal_config_coverage")
        if (
            "最低核销人数" in source_corpus
            and "10人" in source_corpus
            and any(term in row[0] for term in ("获奖人数计算", "获奖人数计算与取整"))
            and row[2] != "仅作不可执行数学说明；比例与取整均为来源建议，产品结果待确认"
        ):
            row[2] = "仅作不可执行数学说明；比例与取整均为来源建议，产品结果待确认"
            rules.append("condition_low_count_rounding_coverage")
        if (
            (
                "同一用户在同一圈子内参加多场有效活动，只算 1 人" in source_corpus
                or "同一用户在同一场活动内只能计算一次" in source_corpus
            )
            and any(term in row[0] for term in ("玩家统计去重", "新老玩家统计与去重"))
            and row[2] != "按适用来源范围核对去重规则；统计入口与观察点待确认"
        ):
            row[2] = "按适用来源范围核对去重规则；统计入口与观察点待确认"
            rules.append("condition_participant_dedup_coverage")
        if row != original_coverage_row:
            lines[index] = "| " + " | ".join(row) + " |"
            normalized_case_ids.append(row[1])

    for index, line in enumerate(lines):
        unsupported_terms = _unsupported_implementation_terms(line, source_corpus)
        if unsupported_terms:
            lines[index] = (
                "> 待确认：原内容引用了来源未定义的产品入口或观察点，具体实现假设已移除。"
            )
            rules.append("remove_unsourced_implementation_prose")

    generated_case_id: str | None = None
    if formal_config and "TC-CONFIG-SOURCE" not in content:
        data_rows = [
            _markdown_cells(line)
            for line in lines[header_index + 2 : coverage_index]
            if line.strip().startswith("|")
        ]
        has_complete_config = data_rows and all(
            any(
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
            for stage, new_price, old_price, budget_floor, minimum in formal_config
        )
        if not has_complete_config:
            source_data = "<br>".join(
                f"第{stage}场：新玩家{new_price}元、老玩家{old_price}元、"
                f"预算底标{budget_floor}元、最低核销{minimum}人"
                for stage, new_price, old_price, budget_floor, minimum in formal_config
            )
            if "第10场以后统一按第10场标准" in normalized_source:
                stage, new_price, old_price, budget_floor, minimum = formal_config[-1]
                source_data += (
                    f"<br>第{stage + 1}场及以后：沿用第{stage}场，新玩家{new_price}元、"
                    f"老玩家{old_price}元、预算底标{budget_floor}元、最低核销{minimum}人"
                )
            deterministic_row = [
                "TC-CONFIG-SOURCE",
                "workspace sources 正式奖励配置表",
                "表驱动核对正式逐场奖励配置",
                "静态配置核对",
                "P0",
                "已取得被测环境当前奖励配置快照",
                source_data,
                "1. 读取当前奖励配置快照<br>2. 按场次逐字段与来源表核对",
                "每场新老玩家奖励、预算底标和最低核销人数均与已确认来源一致",
                "保留配置快照和逐字段差异结果",
                "被测环境配置读取入口待确认",
            ]
            lines.insert(coverage_index, "| " + " | ".join(deterministic_row) + " |")
            coverage_index += 1
            coverage_rows = [_markdown_cells(line) for line in lines[coverage_index + 1 :]]
            coverage_header_offset = next(
                (
                    offset
                    for offset, cells in enumerate(coverage_rows)
                    if _is_coverage_header(cells)
                ),
                None,
            )
            if coverage_header_offset is not None:
                insert_at = coverage_index + 1 + coverage_header_offset + 2
                lines.insert(
                    insert_at,
                    "| 正式奖励配置逐场字段 | TC-CONFIG-SOURCE | "
                    "由来源配置表确定性生成，覆盖全部配置行 |",
                )
            rules.append("source_formal_reward_config")
            generated_case_id = "TC-CONFIG-SOURCE"
    data_rows = [
        _markdown_cells(line)
        for line in lines[header_index + 2 : coverage_index]
        if line.strip().startswith("|")
    ]
    has_complete_combat_case = any(
        _asserts_combat_classification(row) and _has_complete_combat_evidence(row)
        for row in data_rows
    )
    if _source_has_combat_definition(source_corpus) and not has_complete_combat_case:
        combat_row = [
            "TC-COMBAT-SOURCE",
            "workspace sources 对抗类活动定义",
            "同时满足三条件时核对对抗类分类",
            "规则核对",
            "P0",
            "已取得同一活动的玩法规则、胜负或排名规则及活动结果证据",
            "明确对抗关系；明确胜负或排名规则；活动结束后可确认获胜方或排名靠前用户",
            "1. 核对活动的对抗关系<br>2. 核对胜负或排名规则<br>3. 核对结束后的可确认结果",
            "同一活动同时满足三个来源条件，可按来源定义归类为对抗类",
            "保存玩法规则、胜负或排名规则和活动结果三类证据",
            "系统分类入口与结果观察点待确认",
        ]
        lines.insert(coverage_index, "| " + " | ".join(combat_row) + " |")
        coverage_index += 1
        coverage_rows = [_markdown_cells(line) for line in lines[coverage_index + 1 :]]
        coverage_header_offset = next(
            (offset for offset, cells in enumerate(coverage_rows) if _is_coverage_header(cells)),
            None,
        )
        if coverage_header_offset is not None:
            insert_at = coverage_index + 1 + coverage_header_offset + 2
            lines.insert(
                insert_at,
                "| 对抗类活动三条件同时成立 | TC-COMBAT-SOURCE | "
                "由来源定义确定性生成，三类证据必须属于同一活动 |",
            )
        rules.append("source_combat_definition")
    if not rules:
        return content, None
    enriched = "\n".join(lines)
    if content.endswith("\n"):
        enriched += "\n"
    return enriched, {
        "artifact": artifact,
        "rules": sorted(set(rules)),
        "source_rows": len(formal_config),
        "generated_case_id": generated_case_id,
        "normalized_case_ids": sorted(set(normalized_case_ids)),
    }
