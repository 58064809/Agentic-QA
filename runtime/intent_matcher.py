from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def match_intent(user_text: str) -> str | None:
    text = user_text.lower()
    mapping = {
        'requirement_analysis': ['需求分析', '测试点', '风险点', '规则梳理'],
        'test_case_generation': ['写用例', '测试用例', '前置条件', '预期结果'],
        'test_execution': ['pytest', '跑用例', '执行用例', 'smoke', '冒烟', '回归'],
        'result_analysis': ['失败原因', 'traceback', 'allure', '报错分析'],
        'log_analysis': ['日志', 'error', 'traceid', '根因', '异常栈'],
    }
    for intent, keywords in mapping.items():
        for keyword in keywords:
            if keyword.lower() in text:
                return intent
    return None
