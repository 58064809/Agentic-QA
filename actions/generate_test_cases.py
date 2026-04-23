from __future__ import annotations

from typing import Any

from actions.requirement_parser import derive_business_rules
from actions.requirement_parser import derive_risks
from actions.requirement_parser import extract_requirement_items
from actions.requirement_parser import split_questions
from actions.automation_standards import automation_guidance
from actions.test_model_builder import build_test_model

COLUMNS = ["用例ID", "模块", "优先级", "用例标题", "前置条件", "测试数据", "测试步骤", "预期结果", "校验点", "需求来源"]


def _escape_markdown_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def render_markdown_table(columns: list[str], cases: list[dict[str, str]]) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for case in cases:
        lines.append("| " + " | ".join(_escape_markdown_cell(case.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


def _doc_text(requirement_context: dict[str, Any], requirement_items: list[str]) -> str:
    docs = "\n".join(
        document.get("content", "")
        for document in requirement_context.get("selected_requirement_docs", [])
        if document.get("content")
    )
    prototypes = "\n".join(asset.get("path", "") for asset in requirement_context.get("selected_prototypes", []))
    return "\n".join([docs, prototypes, "\n".join(requirement_items)])


def _contains(text: str, *keywords: str) -> bool:
    return any(keyword in text for keyword in keywords)


def _case(
    case_id: str,
    module: str,
    priority: str,
    title: str,
    precondition: str,
    test_data: str,
    steps: list[str],
    expected: list[str],
    checkpoints: list[str],
    source: str,
) -> dict[str, str]:
    return {
        "用例ID": case_id,
        "模块": module,
        "优先级": priority,
        "用例标题": title,
        "前置条件": precondition,
        "测试数据": test_data,
        "测试步骤": "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1)),
        "预期结果": "\n".join(f"{index}. {item}" for index, item in enumerate(expected, start=1)),
        "校验点": "；".join(checkpoints),
        "需求来源": source,
    }


def _deposit_cases(text: str) -> list[dict[str, str]]:
    specs: list[tuple[str, str, str, str, str, str, list[str], list[str], list[str], str, tuple[str, ...]]] = [
        (
            "DEP-P0-001",
            "商家端-提现限制",
            "P0",
            "未缴纳保证金时商家提现入口受限",
            "商家账户存在可提现余额，保证金状态为未缴纳",
            "可提现余额=1000，保证金实缴=0",
            ["登录商家主账号进入账户管理页", "点击提现按钮", "点击提示中的去缴纳入口"],
            ["提现操作被拦截", "提示保证金未缴纳导致提现功能临时限制", "可跳转到缴纳保证金页面"],
            ["页面提示", "按钮状态", "跳转链接", "服务端权限拦截"],
            "若保证金未缴纳，提现功能受限",
            ("未缴纳", "提现功能受限"),
        ),
        (
            "DEP-P0-002",
            "金额计算",
            "P0",
            "应缴总金额按基础保证金和风险保证金取高值",
            "商家已有基础保证金规则和风险保证金规则",
            "基础=5000，风险=8000；基础=10000，风险=3000",
            ["触发应缴金额计算", "分别查看商家端概览和运营端商家详情", "查询接口返回金额字段"],
            ["基础5000/风险8000时应缴总金额=8000", "基础10000/风险3000时应缴总金额=10000", "页面、接口、明细口径一致"],
            ["金额公式", "页面展示", "接口字段", "舍入精度"],
            "应缴总金额计算：基础保证金和风险保证金两者金额就高原则",
            ("应缴总金额", "基础保证金", "风险保证金"),
        ),
        (
            "DEP-P0-003",
            "金额计算",
            "P0",
            "基础保证金按一般保证金和特殊类目保证金取高值",
            "商家经营类目命中一般保证金和特殊类目保证金",
            "一般=3000，特殊类目=6000；一般=8000，特殊类目=5000",
            ["配置店铺类型基础保证金和特殊类目保证金", "触发商家应缴基础保证金计算", "查看商家端应缴基础保证金"],
            ["取两者较高金额作为应缴基础保证金", "多类目时按规则选中最高约束", "运营端与商家端展示一致"],
            ["规则优先级", "多类目", "配置读取", "展示一致性"],
            "基础保证金计算说明：按照一般保证金和特殊类目保证金两者金额就高原则收取",
            ("基础保证金", "特殊类目"),
        ),
        (
            "DEP-P0-004",
            "缴纳保证金",
            "P0",
            "网银转账提交凭证后进入待审核且不立即入账",
            "商家待缴金额大于0，财务收款账户配置有效",
            "缴存金额=1000，凭证=JPG/PDF，小于5MB",
            ["进入缴纳保证金页", "输入合法缴存金额并上传凭证", "提交审核", "刷新保证金概览和明细"],
            ["提交成功生成缴纳申请", "申请状态为待审核", "保证金余额/可用金额不提前增加", "明细记录可追踪凭证和提交时间"],
            ["申请状态", "余额不提前变化", "凭证存储", "流水/明细"],
            "填写缴存金额 → 上传转账凭证 → 提交审核 → 等待财务审核",
            ("网银转账", "待审核", "上传凭证"),
        ),
        (
            "DEP-P0-005",
            "缴纳保证金",
            "P0",
            "财务审核通过后保证金入账并更新状态",
            "存在待审核缴纳申请，财务专员账号可审核",
            "审核结果=通过，缴存金额=1000",
            ["财务专员进入审核页", "审核通过缴纳申请", "查看商家保证金概览、明细、通知", "重复刷新页面和接口"],
            ["已缴存金额增加1000", "可用金额、待缴金额、保证金状态重新计算", "生成入账明细并通知商家", "重复刷新不重复入账"],
            ["余额变更", "状态流转", "流水", "通知", "幂等"],
            "财务审核通过后更新余额",
            ("审核通过", "更新余额"),
        ),
        (
            "DEP-P0-006",
            "缴纳保证金",
            "P0",
            "财务审核失败后通知商家且允许重新上传凭证",
            "存在待审核缴纳申请，财务专员账号可审核",
            "审核结果=失败，失败原因=凭证不清晰",
            ["财务专员驳回缴纳申请", "商家查看通知和缴纳记录", "商家重新上传凭证并再次提交"],
            ["原申请状态变为审核失败", "保证金余额不增加", "商家收到失败原因", "允许重新上传并生成新的待审核记录"],
            ["失败状态", "余额不变", "失败原因", "重新提交链路"],
            "审核失败：通知商家，允许重新上传凭证",
            ("审核失败", "重新上传"),
        ),
        (
            "DEP-P0-007",
            "字段校验",
            "P0",
            "缴存金额必填、最小值和最大值校验",
            "商家待缴金额为1000",
            "空值、0、0.99、1.00、1000、2000、2000.01、负数、三位小数",
            ["分别输入各类金额提交缴纳申请", "观察前端提示", "绕过前端直接调用接口提交非法金额"],
            ["空值、低于1、超过应缴2倍、负数、精度非法均被拦截", "1.00和不超过上限的合法金额可提交", "前端和服务端校验一致"],
            ["必填", "边界值", "小数精度", "服务端兜底"],
            "缴存金额：必填，最小金额¥1.00，不能超过应缴金额的2倍",
            ("缴存金额", "必填", "最小金额", "2倍"),
        ),
        (
            "DEP-P1-008",
            "字段校验",
            "P1",
            "转账凭证格式和大小校验",
            "商家进入缴纳保证金页",
            "JPG 4.9MB、PDF 5MB、PNG、DOCX、EXE、PDF 5.1MB",
            ["上传不同格式和大小的凭证", "提交缴纳申请", "查看接口返回和页面提示"],
            ["JPG/PDF且大小不超过5MB可上传", "不支持格式或超大文件被拦截", "失败提示明确且不生成待审核申请"],
            ["文件格式", "文件大小", "安全拦截", "失败无脏数据"],
            "转账凭证：支持JPG、PDF格式，大小≤5MB",
            ("转账凭证", "JPG", "PDF", "5MB"),
        ),
        (
            "DEP-P0-009",
            "支付方式",
            "P0",
            "缴纳保证金不支持支付宝/微信等第三方支付",
            "商家进入缴纳保证金页",
            "支付方式=支付宝/微信/网银转账",
            ["查看页面支付方式入口", "尝试通过接口传入第三方支付方式", "提交网银转账方式"],
            ["页面不提供支付宝/微信可用入口", "接口拒绝第三方支付方式", "网银转账链路可正常提交"],
            ["PRD/原型差异", "页面入口", "接口枚举", "服务端兜底"],
            "不支持第三方支付（支付宝/微信支付）",
            ("第三方支付", "支付宝", "微信"),
        ),
        (
            "DEP-P0-010",
            "状态机",
            "P0",
            "保证金状态 UNPAID/PAID/INSUFFICIENT 正确流转",
            "准备三类商家：未缴纳、足额缴纳、不足额缴纳",
            "实缴=0；实缴=应缴；0<实缴<应缴",
            ["分别打开商家端保证金概览", "查看运营端商家保证金状态", "触发补缴或审核通过后重新查看状态"],
            ["实缴0展示未缴纳", "实缴大于等于应缴展示已缴纳", "实缴小于应缴展示不足额/待补缴", "补缴审核通过后状态刷新"],
            ["状态枚举", "金额关系", "页面/接口一致", "补缴流转"],
            "UNPAID / PAID / INSUFFICIENT 状态枚举",
            ("UNPAID", "PAID", "INSUFFICIENT"),
        ),
        (
            "DEP-P0-011",
            "0元入驻",
            "P0",
            "0元入驻商家按最高冻结比例和最高冻结上限冻结货款",
            "商家为0元入驻，经营多个类目且类目冻结配置不同",
            "类目A冻结比例10%上限1000，类目B冻结比例20%上限500",
            ["产生多笔待结算订单", "触发结算冻结", "累计冻结接近并达到上限", "查看账户余额和冻结明细"],
            ["冻结比例取已经营类目最高比例", "冻结金额上限取最高上限", "累计达到上限后不再继续冻结", "冻结明细可追溯到结算单"],
            ["最高比例", "最高上限", "累计冻结", "不超冻结上限"],
            "0 元入驻商家冻结规则",
            ("0 元入驻", "冻结比例", "冻结金额上限"),
        ),
        (
            "DEP-P0-012",
            "冻结/解冻",
            "P0",
            "足额缴纳保证金后释放已冻结金额",
            "商家存在因保证金不足产生的冻结金额",
            "实缴金额从不足额补缴到大于等于应缴金额",
            ["商家补缴保证金并提交凭证", "财务审核通过", "查看冻结金额、可用余额、冻结明细"],
            ["保证金状态变为已缴纳", "符合释放条件的冻结金额解冻回可用余额", "生成解冻明细", "不会重复解冻"],
            ["解冻条件", "可用余额", "流水", "幂等"],
            "足额缴纳后的处理：解除账户中的冻结金额",
            ("足额缴纳", "解除账户中的冻结金额"),
        ),
        (
            "DEP-P0-013",
            "配置管理",
            "P0",
            "保证金配置单项保存后实时生效",
            "超级管理员登录运营端，存在可编辑保证金配置",
            "基础保证金从5000调整为8000",
            ["编辑基础保证金配置并保存", "立即查看受影响商家应缴金额", "同时发起商家缴纳/补缴操作", "查询配置变更记录"],
            ["配置保存后立即生效", "商家应缴金额按新规则计算", "并发操作不出现新旧规则混用", "变更记录可审计"],
            ["实时生效", "存量商家", "并发", "审计"],
            "配置新增/修改实时生效",
            ("实时生效", "配置管理"),
        ),
        (
            "DEP-P0-014",
            "违规扣罚",
            "P0",
            "违规罚单审核通过后执行保证金扣罚",
            "商家存在可扣罚保证金，运营端有罚单审核权限",
            "扣罚金额=500，处罚对象=商家/商品",
            ["运营专员创建违规罚单", "有权限角色审核通过", "执行扣罚", "查看商家保证金余额、罚单状态、资金明细"],
            ["罚单状态按待审核/待执行/执行中/已执行流转", "保证金余额减少扣罚金额", "生成扣罚流水", "通知商家且详情可追溯"],
            ["状态流转", "扣罚金额", "流水", "通知"],
            "违规罚单流程、执行扣罚",
            ("违规", "罚单", "扣罚"),
        ),
        (
            "DEP-P1-015",
            "违规申诉",
            "P1",
            "商家在申诉期内可申诉且超过次数后不可继续申诉",
            "商家存在待审核/可申诉罚单",
            "申诉期=3天，最多3轮",
            ["商家提交第1轮申诉", "平台驳回后继续提交至第3轮", "尝试第4轮申诉", "申诉通过一笔罚单"],
            ["申诉期内可提交申诉", "最多允许3轮", "第4轮被拦截", "申诉通过后罚单撤销且不执行扣罚"],
            ["申诉期", "次数限制", "状态互斥", "扣罚阻断"],
            "申诉期内支持申诉，最多3轮",
            ("申诉", "最多 3 轮", "3 天"),
        ),
        (
            "DEP-P0-016",
            "退店",
            "P0",
            "退店申请必须同时满足所有退店条件",
            "商家存在商品、订单、售后、佣金、货款、保证金等检查项",
            "每次构造一个条件不满足，其余条件满足",
            ["逐项构造退店条件未通过场景", "进入退店申请页", "尝试提交退店申请", "全部条件满足后再次提交"],
            ["任一条件未通过时不可提交", "页面展示具体未通过原因和数量", "全部通过后才可提交并进入观察期"],
            ["条件并集", "阻断提交", "原因展示", "观察期入口"],
            "退店条件校验需同时满足",
            ("退店条件", "观察期"),
        ),
        (
            "DEP-P0-017",
            "退店提取",
            "P0",
            "观察期结束后可提取全部保证金且支持修改收款账户",
            "商家已进入退店观察期且观察期结束",
            "保证金余额=3000，默认账户A，选择账户B",
            ["进入观察期后提取页面", "点击提取保证金", "将收款账户改为其他已绑定账户", "提交提取申请"],
            ["提取金额固定为全部保证金余额", "可选择其他已绑定收款账户", "提交后进入财务审核/处理", "原路退回限制不再生效"],
            ["提取金额", "收款账户", "审核状态", "账户绑定"],
            "观察期结束后，商家提取保证金；支持修改收款账户",
            ("观察期", "提取保证金", "收款账户"),
        ),
        (
            "DEP-P0-018",
            "权限",
            "P0",
            "高风险操作按角色权限控制并防止越权",
            "准备商家主账号、商家子账号、运营专员、运营组长、超级管理员、财务专员",
            "操作=缴纳/提取/配置/审核/扣罚/查看财务明细",
            ["分别使用不同角色访问页面和接口", "尝试执行不属于该角色的高风险操作", "检查操作日志"],
            ["无权限角色页面按钮不可用或不可见", "绕过前端调用接口被拒绝", "有权限角色可正常操作", "越权尝试被记录"],
            ["RBAC", "服务端鉴权", "跨商家隔离", "审计日志"],
            "用户角色与权限",
            ("角色", "权限"),
        ),
        (
            "DEP-P0-019",
            "幂等并发",
            "P0",
            "重复提交和并发审核不会重复入账/扣罚/解冻",
            "存在待审核缴纳申请、待执行扣罚单、待解冻记录",
            "同一请求重复点击10次，并发2个审核请求",
            ["对提交、审核、扣罚、解冻操作进行重复点击", "并发调用相同接口", "查询余额、流水、状态和日志"],
            ["同一业务单只产生一次资金副作用", "流水不重复", "最终状态唯一", "重复请求返回明确结果"],
            ["幂等键", "并发锁", "流水唯一性", "最终一致性"],
            "资金操作需要防重复提交",
            ("缴纳", "审核", "扣罚", "解冻"),
        ),
        (
            "DEP-P1-020",
            "统计报表",
            "P1",
            "保证金统计报表与明细数据口径一致",
            "存在不同保证金状态、缴纳、扣罚、冻结、提取记录",
            "时间范围=本月，商家状态=全部/未缴纳/不足额/已缴纳",
            ["进入运营端统计报表", "按时间、状态、商家筛选", "导出报表", "与明细查询和数据库汇总核对"],
            ["统计金额与明细汇总一致", "筛选条件生效", "导出字段完整", "无权限用户不可查看敏感财务数据"],
            ["统计口径", "筛选", "导出", "权限"],
            "统计报表、明细查询、导出",
            ("统计报表", "导出", "明细"),
        ),
    ]

    return [
        _case(case_id, module, priority, title, precondition, test_data, steps, expected, checkpoints, source)
        for case_id, module, priority, title, precondition, test_data, steps, expected, checkpoints, source, triggers in specs
        if any(trigger in text for trigger in triggers)
    ]


def _generic_cases(business_rules: list[str]) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for index, item in enumerate(business_rules[:30], start=1):
        priority = "P0" if any(marker in item for marker in ("必须", "仅", "只能", "不能", "不可", "金额", "权限")) else "P1"
        cases.append(
            _case(
                f"REQ-{index:03d}",
                "需求规则",
                priority,
                item[:60],
                "需求相关账号、数据、依赖服务和环境已准备完成",
                "按 PRD 构造正常值、边界值、异常值",
                ["进入对应功能页面或调用接口", f"执行与“{item}”对应的业务操作", "校验页面、接口、数据库、日志结果"],
                [f"系统行为符合“{item}”描述", "失败场景有明确提示且不产生脏数据", "关键操作有日志或流水可追溯"],
                ["页面", "接口", "数据", "日志"],
                item,
            )
        )
    return cases


def generate_test_cases(user_text: str, requirement_context: dict[str, Any]) -> dict[str, Any]:
    items = extract_requirement_items(user_text, requirement_context)
    requirement_items, parser_questions = split_questions(items)
    business_rules = derive_business_rules(requirement_items)
    model = build_test_model(
        user_text=user_text,
        requirement_context=requirement_context,
        requirement_items=requirement_items,
        business_rules=business_rules,
        generic_risks=derive_risks(requirement_items),
        existing_questions=parser_questions,
    )
    text = "\n".join([user_text, _doc_text(requirement_context, requirement_items)])
    cases = _deposit_cases(text) if _contains(text, "保证金") else []
    if not cases:
        cases = _generic_cases(business_rules)
    if not cases:
        cases = [
            _case(
                "REQ-001",
                "需求输入",
                "P1",
                "补充明确需求后重新生成测试用例",
                "当前未发现可用 PRD 或明确需求条目",
                "PRD 路径、原型路径、需求包名称",
                ["补充或指定需求文档", "重新生成测试用例"],
                ["能够基于明确需求生成可执行测试用例表"],
                ["需求材料完整性"],
                user_text,
            )
        ]

    return {
        "_ok": True,
        "_metadata": {
            "case_count": len(cases),
            "strategy": "deposit_domain" if _contains(text, "保证金") else "generic_rules",
        },
        "task": "test_case_generation",
        "analysis_basis": {
            "requirement_package": requirement_context.get("requirement_package"),
            "requirement_docs": [doc["path"] for doc in requirement_context.get("selected_requirement_docs", [])],
            "prototype_assets": [asset["path"] for asset in requirement_context.get("selected_prototypes", [])],
        },
        "generation_strategy": [
            "按资金系统测试模型生成用例：金额、状态、权限、审核、冻结、扣罚、退店、报表",
            "P0 优先覆盖资金副作用、状态机、权限、幂等和服务端兜底",
            "按等价类、边界值、判定表、状态迁移和场景法组织覆盖",
            "每条用例保留测试数据、步骤、预期结果和校验点，便于直接转入用例管理表",
        ],
        "automation_guidance": automation_guidance(),
        "case_groups": model.get("case_groups", []),
        "open_questions": model.get("open_questions", parser_questions),
        "columns": COLUMNS,
        "case_count": len(cases),
        "cases": cases,
        "markdown_table": render_markdown_table(COLUMNS, cases),
    }
