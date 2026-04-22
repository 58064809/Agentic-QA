from __future__ import annotations

from typing import Any


def analyze_pytest_result(raw_text: str) -> dict[str, Any]:
    """最小 pytest 结果分析器。

    当前版本优先识别几类高频结果：
    - 0 条用例被选中
    - 路径不存在
    - 断言失败
    - 超时
    - 连接问题
    - 全部通过 / 正常结束
    """
    text = raw_text.lower()

    error_type = 'unknown'
    possible_causes: list[str] = []
    next_actions: list[str] = []

    if 'file or directory not found' in text:
        error_type = 'path_not_found'
        possible_causes = [
            'pytest 执行目标路径不存在',
            '当前工作目录不正确，导致相对路径解析错误',
        ]
        next_actions = [
            '检查 target 参数是否存在',
            '检查 pytest 的 cwd 是否为仓库根目录',
        ]
    elif '0 selected' in text or '0 deselected / 0 selected' in text or 'collected 0 items' in text or 'deselected / 0 selected' in text:
        error_type = 'no_tests_selected'
        possible_causes = [
            'pytest -k 或 -m 的筛选条件没有命中任何测试',
            '测试名称、marker 或目标范围与实际用例不匹配',
        ]
        next_actions = [
            '去掉 -k 或 -m 再执行一次',
            '先执行 pytest tests 确认基础测试可被收集',
            '检查测试函数名、文件名和 marker 是否真的包含目标关键字',
        ]
    elif 'assert' in text or 'assertionerror' in text:
        error_type = 'assertion_error'
        possible_causes = [
            '断言结果与预期不一致',
            '接口返回、页面状态或数据结果发生了变化',
        ]
        next_actions = [
            '查看失败断言位置和实际值',
            '对比预期值、接口返回值和环境数据',
        ]
    elif 'timeout' in text:
        error_type = 'timeout'
        possible_causes = [
            '接口响应超时或等待条件超时',
            '环境性能抖动或依赖服务异常',
        ]
        next_actions = [
            '检查超时位置和依赖服务状态',
            '结合日志确认是否为环境问题',
        ]
    elif 'connection' in text:
        error_type = 'connection_error'
        possible_causes = [
            '网络连接失败或目标服务不可达',
            '测试环境未启动或地址配置错误',
        ]
        next_actions = [
            '检查环境连通性和服务状态',
            '确认域名、端口和配置是否正确',
        ]
    elif 'passed' in text and 'failed' not in text and 'error' not in text:
        error_type = 'passed'
        possible_causes = ['pytest 执行完成，未发现失败信息']
        next_actions = ['可以进一步整理通过数量和执行耗时，用于测试报告输出']

    return {
        'task': 'result_analysis',
        'error_type': error_type,
        'summary': raw_text[:500],
        'possible_causes': possible_causes,
        'next_actions': next_actions,
    }
