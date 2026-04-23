from __future__ import annotations

import re
from typing import Any


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = " ".join(item.strip().split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _doc_text(requirement_context: dict[str, Any]) -> str:
    return "\n".join(
        document.get("content", "")
        for document in requirement_context.get("selected_requirement_docs", [])
        if document.get("content")
    )


def _contains(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _evidence_lines(text: str, keywords: tuple[str, ...], limit: int = 5) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*+]\s+|#{1,6}\s*|\d+[.)、]\s*)", "", raw_line).strip()
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = re.sub(r"^(?:功能描述|核心功能|业务规则|字段定义|账户信息展示)[:：]\s*", "", line)
        line = line.strip("|").strip()
        if not line or len(line) > 180:
            continue
        if any(keyword in line for keyword in keywords):
            lines.append(line.rstrip("。；;!?！？"))
    return _unique(lines)[:limit]


def _prototype_label(path: str) -> str:
    name = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    mapping = {
        "merchant-account-management": "商家账户管理/保证金概览",
        "merchant-settlement-deposit": "商家缴纳保证金",
        "merchant-shop-closure": "商家退店申请",
        "merchant-shop-exited": "商家已退出",
        "merchant-violation-management": "商家端违规管理",
        "merchant-withdraw-after-observation": "观察期后提取",
        "platform-deposit-config": "运营端保证金配置",
        "platform-deposit-detail": "运营端保证金明细",
        "platform-deposit-merchant": "运营端商家保证金管理",
        "platform-deposit-report": "运营端保证金统计报表",
        "platform-violation-management": "运营端违规/扣罚管理",
    }
    for key, label in mapping.items():
        if key in name:
            return f"{name}：{label}"
    return name


def _prototype_coverage(requirement_context: dict[str, Any]) -> list[str]:
    coverage: list[str] = []
    for asset in requirement_context.get("selected_prototypes", []):
        line = _prototype_label(asset.get("path", ""))
        if asset.get("size_bytes") == 0:
            line += "（文件为空，需要补原型内容或确认该页面是否取消）"
        coverage.append(line)
    return coverage


def build_requirement_conclusion(
    user_text: str,
    requirement_context: dict[str, Any],
    requirement_items: list[str],
) -> list[str]:
    package = requirement_context.get("requirement_package") or {}
    docs = requirement_context.get("selected_requirement_docs", [])
    prototypes = requirement_context.get("selected_prototypes", [])
    focus = "、".join(requirement_context.get("query_tokens", [])) or user_text
    package_name = package.get("name") or "当前工作区"

    return [
        f"本次命中需求包：{package_name}；分析焦点：{focus}",
        f"已读取 {len(docs)} 个需求文档、关联 {len(prototypes)} 个原型/设计稿，按 PRD 为主、原型为页面覆盖校验依据",
        f"已抽取 {len(requirement_items)} 条可测试需求项；后续用例应围绕业务规则、资金状态、权限边界和异常兜底展开",
    ]


def build_business_objects(text: str) -> list[str]:
    object_specs = [
        (("保证金账户", "保证金概览", "保证金余额", "保证金"), "保证金账户：承载应缴、实缴、可用、待缴、冻结、扣罚、提取等余额视图"),
        (("商家账户", "可提现余额", "待结算金额"), "商家账户：承载货款提现、冻结货款、绑定提现账户和账户状态"),
        (("缴纳", "转账凭证", "网银转账"), "缴纳申请/转账凭证：商家提交缴存金额与凭证，财务审核后入账"),
        (("配置", "基础保证金", "特殊配置", "风险保证金"), "保证金配置规则：决定不同商家、类目、风险场景下的应缴金额"),
        (("违规", "罚单", "扣罚", "申诉"), "违规罚单/扣罚单：连接处罚对象、扣罚金额、申诉、审核和执行"),
        (("冻结", "解冻"), "冻结记录：约束资金占用、解冻、扣罚前后的余额一致性"),
        (("退店", "观察期", "提取保证金"), "退店/提取申请：校验退店条件、观察期、保证金提取和货款提现"),
        (("流水", "明细", "变动记录"), "资金流水/明细：记录每次缴纳、扣罚、冻结、解冻、调整、提取的可追溯凭证"),
        (("统计报表", "报表", "导出"), "统计报表：面向运营/财务统计保证金规模、风险和异常商家"),
    ]
    return [description for keywords, description in object_specs if _contains(text, keywords)]


def build_roles_permissions(text: str) -> list[str]:
    role_specs = [
        (("商家主账号",), "商家主账号：查看保证金概览、缴纳保证金、查看明细、申请退店、提取保证金和货款"),
        (("商家子账号",), "商家子账号：按授权查看保证金概览和明细，不应默认具备缴纳/提取等高风险操作"),
        (("运营专员",), "运营专员：查看商家列表、调整保证金、发起扣罚申请、查看明细、添加违规罚单"),
        (("运营组长",), "运营组长：审核扣罚申请、审核申诉、审核违规罚单"),
        (("超级管理员",), "超级管理员：配置保证金规则、审核高金额扣罚、查看统计报表"),
        (("财务专员",), "财务专员：审核网银转账、处理退款、查看财务明细"),
        (("法务专员",), "法务专员：审核重大扣罚、处理申诉纠纷"),
    ]
    return [description for keywords, description in role_specs if _contains(text, keywords)]


def build_funds_model(text: str) -> list[str]:
    amount_specs = [
        (("应缴总金额",), "应缴总金额：按基础保证金和风险保证金金额就高原则计算"),
        (("基础保证金",), "应缴基础保证金：按一般保证金和特殊类目保证金金额就高原则计算"),
        (("风险保证金",), "应缴风险保证金：受风险规则、处罚或商家状态影响"),
        (("已缴存金额",), "已缴存金额：财务审核通过后才应增加，不应在待审核阶段入账"),
        (("还需缴存金额", "待缴金额"), "待缴/还需缴存金额：应缴金额减可用金额，不能出现负数或展示歧义"),
        (("可用金额",), "可用金额：实缴金额减冻结金额，扣罚、冻结、解冻后必须重新计算"),
        (("冻结金额",), "冻结金额：用于约束违规、保证金不足或退店观察期内的资金占用"),
        (("可提现余额",), "可提现余额：受保证金缴纳状态影响，未缴纳时提现入口应受限"),
        (("扣罚金额",), "扣罚金额：执行扣罚时需要校验余额、权限、审核状态和流水一致性"),
        (("提取金额",), "提取金额：观察期结束后默认提取全部保证金余额，需校验收款账户"),
    ]
    return [description for keywords, description in amount_specs if _contains(text, keywords)]


def build_state_model(text: str) -> list[str]:
    states: list[str] = []
    if _contains(text, ("未缴纳", "已缴纳", "不足额", "保证金状态")):
        states.append("保证金状态：未缴纳 -> 待审核/缴纳中 -> 已缴纳；当可用金额低于应缴金额时进入不足额/待补缴")
    if _contains(text, ("待审核", "审核通过", "审核失败", "重新上传")):
        states.append("缴纳凭证状态：待审核 -> 审核通过/审核失败；失败后允许重新上传，成功后才更新余额")
    if _contains(text, ("待执行", "执行中", "已执行", "申诉中", "已驳回", "申诉通过")):
        states.append("违规罚单状态：待审核/申诉中/申诉通过/已驳回/待执行/执行中/已执行，不同状态的按钮和权限必须互斥")
    if _contains(text, ("冻结", "解冻")):
        states.append("冻结状态：冻结中 -> 已解冻/已扣罚；解冻与扣罚不能重复消费同一笔冻结金额")
    if _contains(text, ("退店", "观察期", "已退出")):
        states.append("退店状态：条件校验未通过 -> 可提交 -> 观察期中 -> 可提取 -> 已提取/已提现 -> 已退出")
    return states


def build_core_flows(text: str) -> list[str]:
    flow_specs = [
        (("缴纳", "转账凭证"), "保证金缴纳：填写缴存金额 -> 上传转账凭证 -> 提交审核 -> 财务审核 -> 入账并刷新概览/明细"),
        (("补缴", "待缴"), "保证金补缴：识别待缴金额 -> 限制缴存金额边界 -> 审核通过后恢复可用状态或解除提现限制"),
        (("配置", "实时生效"), "配置管理：新增/编辑配置 -> 单项保存 -> 实时生效 -> 重新影响商家应缴金额"),
        (("违规", "扣罚"), "违规扣罚：创建罚单 -> 商家申诉/平台审核 -> 扣罚审批 -> 执行扣罚 -> 生成流水与状态变更"),
        (("冻结", "解冻"), "冻结/解冻：触发冻结 -> 占用可用金额 -> 解冻或扣罚 -> 校验余额、流水和状态一致"),
        (("退店", "观察期"), "退店提取：退店条件校验 -> 提交申请 -> 观察期 -> 提取保证金/提现货款 -> 完成退出"),
        (("报表", "统计"), "统计报表：按商家、状态、金额、时间维度查询/导出，校验统计口径与明细一致"),
    ]
    return [description for keywords, description in flow_specs if _contains(text, keywords)]


def build_exception_flows(text: str) -> list[str]:
    exceptions = [
        "重复提交缴纳、审核、扣罚、提取操作时必须幂等，不能重复入账、重复扣罚或重复生成流水",
        "金额为空、低于最小值、超过上限、小数精度异常、负数和超大金额必须被前后端一致拦截",
        "权限不足、跨商家访问、越权审核、越权查看财务明细必须被服务端拦截并记录",
    ]
    if _contains(text, ("审核失败", "重新上传", "通知商家")):
        exceptions.append("网银转账审核失败后需通知商家并允许重新上传凭证，原失败记录应保留")
    if _contains(text, ("第三方支付", "支付宝", "微信")):
        exceptions.append("PRD 与原型若对第三方支付描述不一致，需要明确最终口径，避免测试误判")
    if _contains(text, ("0 元入驻", "0元入驻")):
        exceptions.append("0 元入驻商家无需缴纳但仍可能被扣罚，需要验证展示、经营限制和罚单处理是否一致")
    if _contains(text, ("观察期", "延长观察期")):
        exceptions.append("观察期内出现订单、售后或纠纷时，应阻断提取并延长观察期")
    if _contains(text, ("实时生效",)):
        exceptions.append("配置实时生效后需验证存量商家、并发编辑和缓存刷新，避免新旧规则混用")
    return _unique(exceptions)


def build_priority_test_focus(
    requirement_items: list[str],
    business_rules: list[str],
    funds_model: list[str],
    state_model: list[str],
) -> dict[str, list[str]]:
    p0 = [
        "资金金额计算、余额变更、流水落库、状态流转必须一致",
        "缴纳、审核、扣罚、冻结/解冻、提取等核心资金链路不能出现重复或漏处理",
        "高风险操作必须校验角色权限、商家归属和服务端鉴权",
    ]
    if funds_model:
        p0.append(f"重点校验金额模型：{funds_model[0]}")
    if state_model:
        p0.append(f"重点校验状态机：{state_model[0]}")

    p1 = [
        "页面展示、按钮可用性、提示文案、筛选查询、导出结果与 PRD/原型一致",
        "业务规则边界需要覆盖必填、上下限、小数精度、文件格式和文件大小",
        "异常分支需要覆盖审核失败、支付失败、超时、重复提交和配置变更",
    ]
    if business_rules:
        p1.append(f"重点业务规则：{business_rules[0]}")

    p2 = [
        "兼容性、易用性、空数据、长文本、弱网、刷新返回等体验问题",
        "统计报表、列表排序、分页、导出字段和审计留痕的完整性",
    ]
    if requirement_items:
        p2.append(f"补充覆盖需求项：{requirement_items[0]}")

    return {"P0": _unique(p0), "P1": _unique(p1), "P2": _unique(p2)}


def build_risk_list(text: str, generic_risks: list[str]) -> list[str]:
    risks = list(generic_risks)
    risks.extend(
        [
            "资金类需求必须关注金额、状态、流水、权限四者一致，否则容易出现财务对账问题",
            "PRD 写明网银转账，但原型可能展示支付宝/微信入口时，需要先确认支付方式最终口径",
            "配置实时生效会影响存量商家和正在操作的商家，需重点验证并发、缓存和规则回滚",
            "扣罚、冻结、解冻、提取属于高风险操作，必须验证幂等、防重复提交和审计日志",
        ]
    )
    if _contains(text, ("merchant-settlement-deposit.html",)):
        risks.append("缴纳保证金原型文件为空时，页面交互、字段校验和上传凭证细节缺少原型依据")
    return _unique(risks)


def build_case_groups(text: str) -> list[str]:
    groups = [
        "商家端保证金概览与缴纳",
        "网银转账凭证上传与财务审核",
        "金额计算与余额/流水一致性",
        "保证金配置实时生效",
        "运营端商家保证金管理",
        "违规罚单、申诉、扣罚执行",
        "冻结/解冻与提现限制",
        "退店、观察期、保证金提取和货款提现",
        "统计报表、明细查询与导出",
        "权限、幂等、并发和异常兜底",
    ]
    if not _contains(text, ("退店", "观察期")):
        groups = [group for group in groups if "退店" not in group]
    if not _contains(text, ("违规", "罚单", "扣罚")):
        groups = [group for group in groups if "违规" not in group and "扣罚" not in group]
    if not _contains(text, ("报表", "统计", "导出")):
        groups = [group for group in groups if "报表" not in group and "导出" not in group]
    return groups


def build_open_questions(
    text: str,
    existing_questions: list[str],
    requirement_context: dict[str, Any],
) -> list[str]:
    questions = list(existing_questions)
    if _contains(text, ("第三方支付", "支付宝", "微信")) and _contains(text, ("不支持第三方支付",)):
        questions.append("PRD 同时出现原型支持第三方支付展示、缴纳模块又写不支持第三方支付，需要确认最终支付方式")
    if any(asset.get("size_bytes") == 0 for asset in requirement_context.get("selected_prototypes", [])):
        questions.append("存在 0 字节原型文件，需要确认是原型未导出、页面取消，还是后续补充")
    if _contains(text, ("实时生效",)):
        questions.append("配置实时生效对存量商家的重算时机、通知方式、历史记录是否需要明确")
    if _contains(text, ("2个工作日", "1-3个工作日")):
        questions.append("财务审核/到账 SLA 是否需要配置节假日、超时提醒和人工兜底")
    return _unique(questions)


def build_test_model(
    user_text: str,
    requirement_context: dict[str, Any],
    requirement_items: list[str],
    business_rules: list[str],
    generic_risks: list[str],
    existing_questions: list[str],
) -> dict[str, Any]:
    prototype_paths = "\n".join(asset.get("path", "") for asset in requirement_context.get("selected_prototypes", []))
    text = "\n".join([user_text, _doc_text(requirement_context), "\n".join(requirement_items), prototype_paths])
    funds_model = build_funds_model(text)
    state_model = build_state_model(text)

    return {
        "requirement_conclusion": build_requirement_conclusion(user_text, requirement_context, requirement_items),
        "business_objects": build_business_objects(text),
        "roles_permissions": build_roles_permissions(text),
        "page_prototype_coverage": _prototype_coverage(requirement_context),
        "funds_model": funds_model,
        "state_model": state_model,
        "core_flows": build_core_flows(text),
        "exception_flows": build_exception_flows(text),
        "priority_test_focus": build_priority_test_focus(requirement_items, business_rules, funds_model, state_model),
        "risk_list": build_risk_list(text, generic_risks),
        "open_questions": build_open_questions(text, existing_questions, requirement_context),
        "case_groups": build_case_groups(text),
        "evidence": {
            "amount_rules": _evidence_lines(text, ("金额", "保证金", "可用", "待缴", "冻结", "扣罚"), limit=8),
            "state_rules": _evidence_lines(text, ("状态", "待审核", "审核通过", "审核失败", "已执行", "观察期"), limit=8),
            "permission_rules": _evidence_lines(text, ("角色", "权限", "账号", "专员", "管理员"), limit=8),
        },
    }
