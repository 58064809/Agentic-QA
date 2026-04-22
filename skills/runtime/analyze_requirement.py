from __future__ import annotations

from typing import Any


QUESTION_HINTS = ['是否', '需不需要', '支持吗', '怎么', '如何', '待确认']
RISK_HINTS = ['权限', '状态', '边界', '异常', '重复', '并发', '超时', '一致性', '日志']


def analyze_requirement(text: str) -> dict[str, Any]:
    """轻量需求分析器。

    当前版本使用启发式规则，从用户输入里提取：
    - 业务目标
    - 测试点
    - 风险点
    - 待确认项
    """
    cleaned = text.strip()

    business_goal = cleaned
    rules: list[str] = []
    test_points: list[str] = []
    risks: list[str] = []
    pending_questions: list[str] = []

    base_points = [
        '正常流程验证',
        '异常流程验证',
        '边界条件验证',
    ]
    test_points.extend(base_points)

    if '登录' in cleaned:
        rules.append('用户需完成登录后才能访问目标功能')
        test_points.extend(['登录成功场景', '未登录拦截场景', '登录态失效场景'])
    if '注册' in cleaned:
        rules.append('注册需校验输入合法性和重复注册限制')
        test_points.extend(['注册成功场景', '重复注册场景', '非法输入场景'])
    if '下单' in cleaned or '订单' in cleaned:
        rules.append('订单相关能力需关注状态流转和数据一致性')
        test_points.extend(['下单成功场景', '订单状态流转场景', '重复提交场景'])
    if '支付' in cleaned:
        rules.append('支付相关能力需关注结果回调和幂等处理')
        test_points.extend(['支付成功场景', '支付失败场景', '重复支付场景'])
    if '优惠券' in cleaned:
        rules.append('优惠券需校验领取、使用、失效和叠加规则')
        test_points.extend(['优惠券领取场景', '优惠券使用场景', '优惠券失效场景'])
    if '权限' in cleaned or '角色' in cleaned:
        test_points.append('角色和权限边界验证')
        risks.append('存在越权、漏权或错权风险')
    if '状态' in cleaned:
        test_points.append('状态流转和非法状态验证')
        risks.append('状态流转错误可能导致业务异常')
    if '日志' in cleaned:
        risks.append('缺少关键日志会影响问题定位效率')

    for hint in RISK_HINTS:
        if hint in cleaned and all(hint not in risk for risk in risks):
            risks.append(f'需重点关注{hint}相关风险')

    for hint in QUESTION_HINTS:
        if hint in cleaned:
            pending_questions.append('当前需求中存在待确认规则，建议补充明确验收标准')
            break

    # 去重并保序
    def unique(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    return {
        'task': 'requirement_analysis',
        'summary': cleaned[:200],
        'business_goal': business_goal,
        'rules': unique(rules),
        'test_points': unique(test_points),
        'risks': unique(risks),
        'pending_questions': unique(pending_questions),
    }
