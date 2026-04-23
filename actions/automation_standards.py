from __future__ import annotations

TEST_DESIGN_TECHNIQUES = (
    "等价类：同类输入只选代表值，避免重复堆用例",
    "边界值：金额、次数、长度、时间、分页、状态阈值必须覆盖边界内外",
    "判定表：多规则组合、权限矩阵、状态与金额组合用判定表表达",
    "状态迁移：审核、支付、扣罚、退店、冻结/解冻等生命周期必须覆盖合法/非法迁移",
    "场景法：关键端到端链路覆盖主流程、异常流和回滚/补偿",
)

AUTOMATION_CANDIDATE_RULES = (
    "P0 核心链路、高频回归、金额/权限/状态校验优先自动化",
    "依赖人工判断、需求口径未确认、原型缺失的用例先保留手工或待绑定",
    "每条自动化用例必须有稳定前置数据、可观察断言和清理策略",
)

API_TESTING_CHECKLIST = (
    "覆盖成功状态和主要错误码：400/401/403/404/409/422/500",
    "所有关键响应做结构/schema 校验，避免字段变更静默漏测",
    "认证鉴权必须覆盖无 token、过期 token、越权角色和跨租户/跨商家访问",
    "金额、状态、幂等接口必须验证重复请求和并发请求",
    "分页、筛选、排序、空结果、超大 payload 和非法类型必须覆盖",
)

PLAYWRIGHT_CHECKLIST = (
    "优先使用 role/name、label、placeholder、text、test id，避免脆弱 CSS/XPath",
    "禁止硬等待，使用 Playwright 自动等待和 web-first assertion",
    "用 test.step 拆分业务步骤，便于定位失败位置",
    "关键失败保留 trace、screenshot、video 或网络响应证据",
    "用 Page Object/fixture 管理复用逻辑，测试本身保持业务可读",
)

FLAKY_TEST_HEURISTICS = (
    "本地通过 CI 失败：优先检查环境差异、时序等待、服务依赖和数据隔离",
    "偶发超时：优先检查硬等待、动画/遮罩、网络波动和异步状态",
    "顺序相关失败：优先检查共享状态、数据清理和测试间依赖",
    "跨浏览器差异：优先检查渲染差异、定位器和浏览器兼容逻辑",
    "重试后通过：不能直接忽略，应标记 flaky 并补证据和修复计划",
)

TESTING_ANTI_PATTERNS = (
    "只测 happy path，不测错误状态和权限边界",
    "断言实现细节，不断言用户可观察结果或数据状态",
    "测试之间共享可变状态，导致顺序依赖",
    "使用硬等待、脆弱选择器或过度依赖截图",
    "过度 mock 内部逻辑，导致测试通过但生产行为未覆盖",
    "缺少 schema/契约校验，接口字段变化无法及时暴露",
)


def automation_guidance() -> dict[str, list[str]]:
    return {
        "test_design_techniques": list(TEST_DESIGN_TECHNIQUES),
        "automation_candidate_rules": list(AUTOMATION_CANDIDATE_RULES),
        "api_testing_checklist": list(API_TESTING_CHECKLIST),
        "playwright_checklist": list(PLAYWRIGHT_CHECKLIST),
        "flaky_test_heuristics": list(FLAKY_TEST_HEURISTICS),
        "testing_anti_patterns": list(TESTING_ANTI_PATTERNS),
    }
