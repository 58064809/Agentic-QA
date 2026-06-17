from __future__ import annotations

from runtime.graph.state import QAWorkflowState

# ── 意图关键词路由表 ──────────────────────────────────────────
# 源自 COMMANDS.md 「路由表」+「常见中文触发表达」
# 每个意图包含一组触发关键词（匹配时按优先级降序排列）

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "archive": (
        # 归档
        "归档",
        "archive",
    ),
    "bug_draft": (
        # 缺陷草稿
        "缺陷",
        "bug",
        "bug草稿",
        "缺陷报告",
        "提缺陷",
        "真实缺陷",
    ),
    "failure_analysis": (
        # 失败分析
        "失败",
        "失败日志",
        "失败原因",
        "日志分析",
        "看日志",
        "分类失败",
    ),
    "test_execution": (
        # 测试执行
        "跑测试",
        "执行测试",
        "执行自动化",
        "运行测试",
        "收集结果",
        "pytest",
    ),
    "report_generation": (
        # QA 报告
        "报告",
        "qa报告",
        "测试报告",
        "风险结论",
        "汇总测试结果",
        "报告草稿",
    ),
    "api_test_generation": (
        # API 测试
        "接口",
        "api",
        "接口自动化",
        "接口测试",
        "pytest草稿",
        "接口文档",
    ),
    "ui_test_generation": (
        # UI 测试
        "ui",
        "playwright",
        "端到端",
        "e2e",
        "页面测试",
        "登录页面",
    ),
    "requirement_analysis": (
        # 需求分析
        "分析需求",
        "需求分析",
        "拆解需求",
        "拆需求",
        "看prd",
        "看 PRD",
        "读需求",
        "业务规则",
        "提取规则",
        "prd分析",
        # 短关键词（长度小，匹配顺序靠后，但能兜底自然表达如"帮我分析登录需求"）
        # "分析" 在需求分析意图中作为终极 fallback
        "分析",
    ),
    "testcase_generation": (
        # 测试用例生成（优先级最高，放最后以覆盖交集）
        "测试用例",
        "用例",
        "testcase",
        "test case",
        "生成用例",
        "设计用例",
        "生成测试",
        "设计覆盖",
        "补边界",
        "边界用例",
        "回归用例",
    ),
}

# 按关键词长度降序排列，确保长关键词（如"测试用例"）优先于短词（如"用例"）匹配
INTENT_MATCH_LIST: list[tuple[str, str]] = []
for intent, keywords in INTENT_KEYWORDS.items():
    for kw in keywords:
        INTENT_MATCH_LIST.append((kw, intent))
INTENT_MATCH_LIST.sort(key=lambda x: len(x[0]), reverse=True)

ALL_INTENT_DESCRIPTIONS: dict[str, str] = {
    "requirement_analysis": "需求分析",
    "testcase_generation": "测试用例生成",
    "api_test_generation": "API 接口测试生成",
    "ui_test_generation": "UI 端到端测试生成",
    "test_execution": "测试执行",
    "failure_analysis": "失败分析",
    "bug_draft": "缺陷草稿生成",
    "report_generation": "QA 报告生成",
    "archive": "归档",
}

SUPPORTED_LANGGRAPH_INTENTS = {
    "testcase_generation",
    "requirement_analysis",
    "api_test_generation",
    "ui_test_generation",
    "test_execution",
    "failure_analysis",
    "bug_draft",
    "report_generation",
    "archive",
}


def intent_router_node(state: QAWorkflowState) -> QAWorkflowState:
    state.record_node("intent_router_node")
    normalized_input = state.user_input.lower()

    # 第一阶段：关键词精确匹配
    matched_intent: str | None = None
    for keyword, intent in INTENT_MATCH_LIST:
        if keyword in normalized_input:
            matched_intent = intent
            break

    if matched_intent and matched_intent in SUPPORTED_LANGGRAPH_INTENTS:
        state.intent = matched_intent
        return state

    # 第二阶段：匹配了意图但当前 LangGraph 骨架还没实现（预留）
    if matched_intent:
        state.intent = matched_intent
        state.errors.append(
            f"已识别意图「{ALL_INTENT_DESCRIPTIONS.get(matched_intent, matched_intent)}」，"
            f"但当前 LangGraph Skeleton 尚未实现该意图的执行节点。"
        )
        return state

    # 未匹配任何意图
    supported = "、".join(f"「{desc}」" for intent, desc in ALL_INTENT_DESCRIPTIONS.items())
    state.errors.append(
        f"未能识别意图。当前支持：{supported}。\n"
        f"输入示例：\n"
        f"  已支持：分析需求、生成测试用例、生成接口自动化、跑测试、归档\n"
        f"  你的输入：{state.user_input}"
    )
    return state
