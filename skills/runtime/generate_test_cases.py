from __future__ import annotations

from typing import Any


def _build_case(title: str, priority: str, precondition: str, steps: str, expected: str) -> dict[str, str]:
    return {
        '标题': title,
        '优先级': priority,
        '前置条件': precondition,
        '测试步骤': steps,
        '预期结果': expected,
    }


def generate_test_cases(text: str) -> dict[str, Any]:
    """轻量测试用例生成器。

    当前版本根据输入中的高频业务词，生成基础可用的测试用例行。
    输出结构保持固定，便于后续直接渲染为 Markdown 表格。
    """
    cleaned = text.strip()
    cases: list[dict[str, str]] = []

    cases.append(
        _build_case(
            title='通用-正常流程验证',
            priority='P1',
            precondition='功能已正确配置，测试环境可用',
            steps='1. 进入目标功能\n2. 按正常流程执行\n3. 提交或保存',
            expected='功能执行成功，页面/接口返回结果正确',
        )
    )
    cases.append(
        _build_case(
            title='通用-异常输入验证',
            priority='P2',
            precondition='功能支持输入或条件校验',
            steps='1. 输入非法或缺失数据\n2. 执行目标操作',
            expected='系统正确拦截并给出清晰提示，不产生错误数据',
        )
    )

    if '登录' in cleaned:
        cases.append(
            _build_case(
                title='登录-合法账号密码登录成功',
                priority='P0',
                precondition='存在可用测试账号，网络正常',
                steps='1. 打开登录页\n2. 输入合法账号密码\n3. 点击登录',
                expected='登录成功并跳转到目标页面，登录态生效',
            )
        )
    if '注册' in cleaned:
        cases.append(
            _build_case(
                title='注册-合法信息首次注册成功',
                priority='P0',
                precondition='手机号/账号未被注册',
                steps='1. 打开注册页\n2. 输入合法信息\n3. 提交注册',
                expected='注册成功，系统创建新用户记录',
            )
        )
    if '订单' in cleaned or '下单' in cleaned:
        cases.append(
            _build_case(
                title='订单-正常下单成功',
                priority='P0',
                precondition='商品可售，库存充足，用户已登录',
                steps='1. 选择商品\n2. 提交订单\n3. 观察订单结果',
                expected='订单创建成功，订单状态正确，相关数据落库',
            )
        )
        cases.append(
            _build_case(
                title='订单-重复提交拦截验证',
                priority='P1',
                precondition='已进入下单确认页',
                steps='1. 连续快速点击提交订单\n2. 观察订单创建结果',
                expected='系统正确处理重复提交，不产生重复订单',
            )
        )
    if '支付' in cleaned:
        cases.append(
            _build_case(
                title='支付-支付成功结果回写正确',
                priority='P0',
                precondition='存在待支付订单',
                steps='1. 发起支付\n2. 完成支付\n3. 查看订单状态',
                expected='支付成功后订单状态正确更新，支付结果与订单数据一致',
            )
        )
    if '优惠券' in cleaned:
        cases.append(
            _build_case(
                title='优惠券-满足条件时正常使用',
                priority='P1',
                precondition='账户存在可用优惠券',
                steps='1. 进入结算页\n2. 选择符合条件的优惠券\n3. 提交订单',
                expected='优惠金额计算正确，订单金额与优惠券状态更新正确',
            )
        )

    return {
        'task': 'test_case_generation',
        'input_summary': cleaned[:200],
        'columns': ['标题', '优先级', '前置条件', '测试步骤', '预期结果'],
        'cases': cases,
    }
