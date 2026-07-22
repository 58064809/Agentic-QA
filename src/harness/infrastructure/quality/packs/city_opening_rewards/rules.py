from __future__ import annotations

import re

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
