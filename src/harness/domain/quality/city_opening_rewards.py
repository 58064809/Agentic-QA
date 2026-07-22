from __future__ import annotations

import re
from typing import Any

TESTCASE_HEADERS = (
    "用例ID",
    "需求/规则来源",
    "标题",
    "测试类型",
    "优先级",
    "前置条件",
    "测试数据",
    "测试步骤",
    "预期结果",
    "断言/证据",
    "待确认项",
)
IMPLEMENTATION_OBSERVATION_TERMS = (
    "后台",
    "数据库",
    "日志",
    "管理员",
    "账户余额",
    "奖励账户",
    "个人奖励页面",
    "个人奖励记录",
    "可领取列表",
    "奖励页面",
    "成长金页面",
    "活动管理页面",
    "圈子管理页面",
    "领取按钮",
    "统计接口",
    "审核系统",
    "判定系统",
    "活动属性",
)
LOW_PARTICIPANT_PATTERN = re.compile(
    r"(?:参与人数|核销人数)\s*(?:(?:[:：=]|为)\s*[1-9](?!\d)\s*人?|[1-9]\s*人)"
    r"|核销\s*(?:[:：=]|为)\s*[1-9](?!\d)\s*人?"
    r"|(?:参与|核销)\s*[1-9]\s*人"
    r"|[1-9]\s*人核销"
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


def _append_pending(current: str, note: str) -> str:
    cleaned = current.strip()
    if cleaned in {"", "-", "无", "无。"}:
        return note
    if note in cleaned:
        return cleaned
    return f"{cleaned}；{note}"


def _has_unsourced_reward_config_display(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    text = " ".join(row)
    result = " ".join((row[8], row[9]))
    return (
        "单价" in text
        and any(term in text for term in ("新老玩家", "新玩家", "老玩家"))
        and (
            any(term in result for term in ("页面", "显示", "X元", "Y元"))
            or any(term in row[7] for term in ("查看", "观察", "读取界面"))
        )
        and not any(term in result for term in ("不使用", "不展示", "展示待确认"))
    )


def _source_backed_reward_config_row(row: list[str]) -> list[str]:
    rewritten = list(row)
    rewritten[1] = "workspace sources 正式奖励配置与计算公式"
    rewritten[2] = "按正式配置快照核对奖励计算（已移除模型示意值或展示假设）"
    rewritten[5] = "已取得被测环境的场次、人数和正式奖励配置快照"
    rewritten[6] = "场次及新老玩家人数使用被测环境数据；单价与底标仅取正式配置快照"
    rewritten[7] = "1. 读取正式配置快照<br>2. 按来源公式核对计算输入与过程"
    rewritten[8] = "计算所用单价和底标与正式配置一致；结果由实际人数和来源公式确定"
    rewritten[9] = "保留配置快照、人数输入和计算过程，不使用示意金额或展示假设"
    rewritten[10] = "被测数据、结果观察点、取整与展示规则待确认"
    return rewritten


def _source_has_combat_definition(source: str) -> bool:
    return all(
        term in source
        for term in (
            "明确的对抗关系",
            "明确胜负或排名规则",
            "能确认获胜",
        )
    )


def _source_has_distinct_activity_scopes(source: str) -> bool:
    return (
        "有到场核销 / 签到 / 平台确认记录" in source
        and "App内发布｜报名人数大于5人｜活动实际完成" in source
    )


def _asserts_effective_activity_observation(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    result = " ".join((row[8], row[9]))
    explicit_outcome = any(
        term in result
        for term in (
            "计为有效活动",
            "计为主理人有效活动",
            "计入有效活动",
            "计入奖励有效活动",
            "计入成长金有效活动",
            "不计为有效活动",
            "不计入有效活动",
            "不计入奖励有效活动",
            "不计入成长金有效活动",
            "场次计数",
            "场次数增加",
            "活动数增加",
            "前端展示为有效活动",
        )
    )
    product_observation = "有效活动" in " ".join((row[1], row[2])) and any(
        term in result for term in ("系统", "模块", "列表", "标记", "计数", "统计", "展示")
    )
    return explicit_outcome or product_observation


def _is_reward_condition_case(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    descriptor = " ".join((row[1], row[2], row[5], row[6]))
    return (
        "奖励六条件" in descriptor
        or "领取条件" in row[1]
        or "奖励条件" in row[1]
        or bool(re.search(r"奖励规则[^#]*#01.*(?:六条件|条件\s*[1-6]|多条件)", row[1]))
        or bool(re.search(r"(?<!\d)3(?:18|19|20|21|22|23)(?!\d)", row[1]))
        or (
            "成长金" not in descriptor
            and any(term in descriptor for term in ("领取奖励", "无法领取", "领取失败", "领取成功"))
        )
    )


def _requires_unconfirmed_content_judgment(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    scenario = " ".join((row[1], row[2], row[5], row[6], row[7]))
    content_context = "内容" in scenario or "动态" in scenario
    return any(term in scenario for term in ("真实", "灌水", "刷量", "内容四条件")) or (
        content_context and any(term in scenario for term in ("全部四条件", "四条件全部满足"))
    )


def _asserts_content_count_or_validity(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    result = " ".join((row[8], row[9]))
    return any(
        term in result
        for term in (
            "系统判定",
            "显示内容无效",
            "不计入",
            "计数不增加",
            "数量不变",
            "内容数未增加",
            "内容数不变",
            "计数保持不变",
            "标记为无效",
            "计入",
            "计为",
            "内容数增加",
            "计数+",
            "被计入",
            "被计数",
        )
    )


def _asserts_positive_content_count(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    descriptor = " ".join((row[1], row[2], row[8], row[9]))
    if "内容" not in descriptor and "动态" not in descriptor:
        return False
    result = " ".join((row[8], row[9]))
    if any(
        term in result
        for term in (
            "不计入",
            "未计入",
            "不计数",
            "不增加",
            "未增加",
            "不变",
            "无变化",
            "不产生",
            "不断言",
            "不可执行",
        )
    ):
        return False
    return any(term in result for term in ("计入", "计数", "内容数+", "内容数增加"))


def _has_content_four_conditions(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    scenario = " ".join((row[1], row[2], row[5], row[6], row[7]))
    if any(term in scenario for term in ("全部四条件", "四条件全部满足")):
        return True
    return all(
        check
        for check in (
            any(term in scenario for term in ("对应圈子", "圈子内")),
            any(term in scenario for term in ("活动相关", "内容相关", "与活动相关")),
            "活动期" in scenario,
            any(term in scenario for term in ("真实有效", "非灌水", "真实性")),
        )
    )


def _explicit_new_old_player_count(row: list[str]) -> int | None:
    if len(row) != len(TESTCASE_HEADERS):
        return None
    scenario = " ".join((row[2], row[5], row[6], row[7], row[8], row[9]))
    if not any(term in scenario for term in ("奖金池", "奖励计算", "单价")):
        return None
    each = re.search(r"新老(?:玩家|客户)各\s*(\d+)\s*人", scenario)
    if each:
        return int(each.group(1)) * 2
    new = re.search(r"新(?:玩家|客户)\s*(\d+)\s*人", scenario)
    old = re.search(r"老(?:玩家|客户)\s*(\d+)\s*人", scenario)
    if new and old:
        return int(new.group(1)) + int(old.group(1))
    return None


def _is_no_growth_tier_case(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    descriptor = " ".join(row)
    return ("成长金" in descriptor and "不足" in descriptor) or any(
        term in descriptor
        for term in (
            "不满足任何",
            "未达到任何",
            "未达任何档",
            "所有指标未达",
            "档位1不满足",
            "不足档位1",
            "有效活动数不足",
            "参与玩家不足",
            "内容不足",
            "显示未达标",
            "无成长金",
        )
    )


def _is_growth_fund_case(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    descriptor = " ".join((row[2], row[5], row[6], row[7], row[8], row[9], row[10]))
    if any(term in descriptor for term in ("奖金池", "新玩家单价", "老玩家单价", "预算底标")):
        return False
    return "成长金" in descriptor or "档位" in descriptor


def _is_growth_tier_case(row: list[str]) -> bool:
    if not _is_growth_fund_case(row):
        return False
    descriptor = " ".join(row)
    return any(term in descriptor for term in ("档位", "达标", "不叠加", "最高档"))


def _has_circle_participant_dedup_evidence(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    scenario = " ".join((row[2], row[5], row[6], row[7]))
    return (
        "同一用户" in scenario
        and "同一圈" in scenario
        and any(term in scenario for term in ("多场", "两场", "2场"))
        and any(
            term in row[8]
            for term in (
                "只计 1",
                "只计1",
                "计为 1",
                "计为1",
                "只算 1",
                "只算1",
                "只计算 1",
                "只计算1",
            )
        )
        and "不依赖未确认展示入口" in row[9]
    )


def _is_untriggerable_growth_ranking(row: list[str], source: str) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    if "当前均不限名额" not in source and "当前配置下不会实际触发" not in source:
        return False
    descriptor = " ".join(row)
    return (
        "同档" in descriptor
        and "排序" in descriptor
        and not (row[7].strip() == "不执行" and "当前不限名额配置不会触发" in row[8])
    )


def _is_missing_reward_condition_case(row: list[str]) -> bool:
    if not _is_reward_condition_case(row):
        return False
    descriptor = re.sub(r"\s+", "", " ".join((row[1], row[2], row[5], row[6])))
    return any(
        term in descriptor
        for term in (
            "缺少",
            "缺失",
            "除动态外",
            "未报名",
            "未核销",
            "未进入获奖名单",
            "不在获奖名单",
            "获奖名单不包含",
            "未发布",
            "无话题",
            "未带话题",
            "未@",
            "无@",
        )
    )


def _asserts_positive_reward(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    result = " ".join((row[8], row[9]))
    if any(term in result for term in ("不获得奖励", "无法获得奖励", "无奖励资格")):
        return False
    return any(
        term in result
        for term in ("用户获得", "玩家获得", "获得本场奖励", "胜队玩家获得", "进入获奖名单")
    )


def _has_reward_six_conditions(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    scenario = " ".join((row[2], row[5], row[6], row[7]))
    if "六条件" in row[1] and all(
        term in scenario for term in ("报名", "核销", "获奖名单", "动态", "话题", "@官方号")
    ):
        return True
    return all(
        check
        for check in (
            "报名" in scenario,
            "核销" in scenario,
            "获奖名单" in scenario,
            "趣看" in scenario and "动态" in scenario,
            "#今天一起开局" in scenario,
            "@交子立方" in scenario or "@官方号" in scenario,
        )
    )


def _asserts_combat_classification(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    result = " ".join((row[8], row[9]))
    if any(
        term in result
        for term in (
            "不归类为对抗类",
            "未归类为对抗类",
            "不能归类为对抗类",
            "不被识别为对抗类",
            "不被判定为对抗类",
            "不属对抗类",
            "非对抗类",
            "不标记为对抗类",
            "不按来源定义归类为对抗类",
            "不按对抗类定义归类",
        )
    ):
        return False
    return any(
        term in result
        for term in (
            "归类为对抗类",
            "标记为对抗类",
            "标记为“对抗类”",
            "标识为对抗类",
            "标识为“对抗类”",
            "活动类型为对抗类",
            "识别为对抗类",
            "判定为对抗类",
        )
    )


def _is_combat_case(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    return "对抗" in " ".join((row[1], row[2], row[5], row[6], row[7], row[8], row[9]))


def _is_missing_combat_condition_case(row: list[str]) -> bool:
    if not _is_combat_case(row):
        return False
    scenario = " ".join((row[1], row[2], row[5], row[6]))
    return any(
        term in scenario
        for term in (
            "缺少对抗关系",
            "无对抗关系",
            "无对手",
            "缺少胜负规则",
            "无胜负规则",
            "规则未定义胜负",
            "无法确认结果",
            "无法确认胜负",
            "结果数据丢失",
            "无可靠结果",
            "无有效结果",
        )
    )


def _asserts_partial_combat_product_outcome(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    result = " ".join((row[8], row[9]))
    if any(
        term in result
        for term in (
            "不归类为对抗类",
            "未归类为对抗类",
            "不被识别为对抗类",
            "非对抗类",
            "不按来源定义归类为对抗类",
            "不按对抗类定义归类",
        )
    ):
        return False
    return _asserts_combat_classification(row) or any(
        term in result for term in ("系统", "显示", "展示", "胜队", "胜者")
    )


def _asserts_unsourced_combat_ui(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    if "单项输入不能推导最终分类或展示结果" in row[8]:
        return False
    observation = " ".join((row[7], row[8], row[9]))
    return (
        any(term in observation for term in ("前端", "标识", "提示", "检查是否被标记", "分类入口"))
        and "不断言未定义的前端标识" not in row[9]
    )


def _has_complete_combat_evidence(row: list[str]) -> bool:
    if len(row) != len(TESTCASE_HEADERS):
        return False
    scenario = " ".join((row[2], row[5], row[6], row[7]))
    if any(
        term in scenario
        for term in (
            "无法确认结果",
            "无法确认胜负",
            "结果无法确认",
            "结果丢失",
            "无结果记录",
            "无可靠结果",
            "无有效结果",
            "未记录成绩",
        )
    ):
        return False
    if "对抗" in scenario and any(
        term in scenario for term in ("满足三对抗条件", "满足三项对抗条件", "满足三条件")
    ):
        return True
    has_relation = any(
        term in scenario
        for term in (
            "对抗关系",
            "对抗队伍",
            "队伍对队伍",
            "队伍对抗",
            "两队对抗",
            "两个队伍",
            "个人对个人",
            "多人积分排名",
            "个人积分排名",
            "个人积分赛",
            "1v1",
            " vs ",
            " VS ",
        )
    )
    has_rule = any(
        term in scenario
        for term in (
            "胜负规则",
            "胜败规则",
            "排名规则",
            "得分规则",
            "计分规则",
            "比分多者胜",
            "比分定胜负",
            "按得分",
            "积分排名",
        )
    )
    has_confirmable_result = any(
        term in scenario
        for term in (
            "结束后",
            "确认获胜",
            "可确认结果",
            "排名靠前",
            "活动结果",
            "赛后",
            "活动后",
            "最终排名",
        )
    )
    return has_relation and has_rule and has_confirmable_result


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


def _markdown_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _expand_coverage_case_id_range(value: str) -> str:
    match = re.fullmatch(r"(TC-[A-Za-z0-9-]*?)(\d+)\s*[~～]\s*(\d+)", value.strip())
    if not match:
        return value
    prefix, start_text, end_text = match.groups()
    start = int(start_text)
    end = int(end_text)
    if end < start or end - start > 100:
        return value
    width = max(len(start_text), len(end_text))
    return ", ".join(f"{prefix}{number:0{width}d}" for number in range(start, end + 1))


def _unsupported_implementation_terms(content: str, source: str) -> list[str]:
    unsupported: list[str] = []
    negations = ("不得", "禁止", "未定义", "不应", "不能", "不使用", "删除")
    for term in IMPLEMENTATION_OBSERVATION_TERMS:
        if term in source:
            continue
        claimed = False
        for line in content.splitlines():
            start = 0
            while (position := line.find(term, start)) >= 0:
                local_context = line[
                    max(0, position - 10) : min(len(line), position + len(term) + 10)
                ]
                if not any(negation in local_context for negation in negations):
                    claimed = True
                    break
                start = position + len(term)
            if claimed:
                break
        if claimed:
            unsupported.append(term)
    return unsupported


def _replace_unsupported_terms(content: str, terms: list[str]) -> str:
    replaced = content
    for term in terms:
        replaced = replaced.replace(term, "未确认产品入口或观察点")
    return replaced


def _formal_reward_config(source: str) -> list[tuple[int, int, int, int, int]]:
    rows: list[tuple[int, int, int, int, int]] = []
    pattern = re.compile(
        r"^\|\s*(\d+)\s*\|\s*(\d+)元\s*\|\s*(\d+)元\s*\|\s*(\d+)元\s*\|\s*(\d+)人\s*\|$"
    )
    for line in source.splitlines():
        match = pattern.match(line.strip())
        if match:
            rows.append(tuple(int(value) for value in match.groups()))
    return rows


def _row_covers_reward_config(
    row: list[str],
    *,
    stage: int,
    new_price: int,
    old_price: int,
    budget_floor: int,
    minimum: int,
) -> bool:
    text = re.sub(r"\s+", "", " ".join(row))
    checks = (
        rf"(?:第{stage}场|场次[:=：]?{stage}(?!\d))",
        rf"(?:新玩家|新客户|新)(?:单价|奖励)?[:=：为]?{new_price}元",
        rf"(?:老玩家|老客户|老)(?:单价|奖励)?[:=：为]?{old_price}元",
        rf"(?:预算底标|底标)[:=：为]?{budget_floor}元",
        rf"(?:最低核销人数|最低核销)[:=：为]?{minimum}人",
    )
    return all(re.search(pattern, text) for pattern in checks)


def _incompatible_reward_examples(
    rows: list[list[str]],
    formal_config: list[tuple[int, int, int, int, int]],
) -> list[str]:
    expected = {
        stage: (new_price, old_price, budget_floor, minimum)
        for stage, new_price, old_price, budget_floor, minimum in formal_config
    }
    incompatible: list[str] = []
    stage_pattern = re.compile(r"(?:第(\d+)场|场次[:=：]?\s*(\d+))")
    value_patterns = (
        (
            0,
            re.compile(
                r"(?:新玩家|新客户|新手|新)(?:单价|奖励)?[（(:：为=]?\s*"
                r"(\d+)(?!\d)(?:元|(?![人场条]))"
            ),
        ),
        (
            1,
            re.compile(
                r"(?:老玩家|老客户|老手|老)(?:单价|奖励)?[）):：为=]?\s*"
                r"(\d+)(?!\d)(?:元|(?![人场条]))"
            ),
        ),
        (2, re.compile(r"(?:预算底标|底标)[）):：为=]?\s*(\d+)(?:元)?")),
        (3, re.compile(r"(?:最低核销人数|最低核销)[）):：为=]?\s*(\d+)人")),
    )
    budget_floors = {values[2] for values in expected.values()}
    allowed_new_prices = {float(values[0]) for values in expected.values()}
    allowed_old_prices = {float(values[1]) for values in expected.values()}
    labeled_price_patterns = (
        (
            allowed_new_prices,
            re.compile(r"(?:新玩家|新客户|新)(?:单价|奖励)[:：为=]?\s*(\d+(?:\.\d+)?)元?"),
        ),
        (
            allowed_old_prices,
            re.compile(r"(?:老玩家|老客户|老)(?:单价|奖励)[:：为=]?\s*(\d+(?:\.\d+)?)元?"),
        ),
    )
    for row in rows:
        text = re.sub(r"\s+", "", " ".join(row))
        if any(
            any(float(value) not in allowed for value in pattern.findall(text))
            for allowed, pattern in labeled_price_patterns
        ):
            incompatible.append(row[0])
            continue
        compared_floors = [
            int(value) for value in re.findall(r"奖金池\D*\d+\s*[<>＜＞]\s*(\d+)", text)
        ]
        if any(value not in budget_floors for value in compared_floors):
            incompatible.append(row[0])
            continue
        stages = list(stage_pattern.finditer(text))
        for index, match in enumerate(stages):
            stage = int(match.group(1) or match.group(2))
            expected_stage = stage
            if stage not in expected:
                maximum_stage = max(expected)
                if stage > maximum_stage:
                    expected_stage = maximum_stage
                else:
                    continue
            end = stages[index + 1].start() if index + 1 < len(stages) else len(text)
            segment = text[match.start() : end]
            if any(
                any(
                    int(value) != expected[expected_stage][field]
                    for value in pattern.findall(segment)
                )
                for field, pattern in value_patterns
            ):
                incompatible.append(row[0])
                break
            multipliers = [int(price) for _, price in re.findall(r"(\d+)\s*[×*]\s*(\d+)", segment)]
            if (
                "奖金池" in segment
                and len(multipliers) >= 2
                and tuple(multipliers[:2]) != expected[expected_stage][:2]
            ):
                incompatible.append(row[0])
                break
    return sorted(set(incompatible))


def _is_coverage_header(cells: list[str]) -> bool:
    if len(cells) != 3:
        return False
    rule, testcase, basis = cells
    return (
        any(keyword in rule for keyword in ("规则", "风险", "覆盖"))
        and "用例" in testcase
        and any(keyword in basis for keyword in ("映射", "依据", "说明", "验证"))
    )
