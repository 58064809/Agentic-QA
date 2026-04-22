from __future__ import annotations


def match_intent(user_text: str) -> str | None:
    text = user_text.lower()

    weighted_mapping = [
        ('result_analysis', ['失败结果', '失败原因', 'traceback', 'allure', '报错分析', 'assertionerror', '分析这段']),
        ('log_analysis', ['日志', 'traceid', '根因', '异常栈', '最近30分钟', 'error']),
        ('test_case_generation', ['写用例', '测试用例', '前置条件', '预期结果', 'markdown 表格', 'markdown表格']),
        ('requirement_analysis', ['需求分析', '测试点', '风险点', '规则梳理', '待确认项', '边界场景']),
        ('test_execution', ['执行 pytest', 'pytest 冒烟', '跑用例', '执行用例', 'smoke', '冒烟', '回归', 'pytest']),
    ]

    best_intent: str | None = None
    best_score = 0

    for intent, keywords in weighted_mapping:
        score = sum(1 for keyword in keywords if keyword.lower() in text)
        if score > best_score:
            best_score = score
            best_intent = intent

    return best_intent if best_score > 0 else None
