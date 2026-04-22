from runtime.intent_matcher import match_intent


def test_match_requirement_analysis() -> None:
    assert match_intent('请分析这个需求并输出测试点和风险点') == 'requirement_analysis'


def test_match_test_case_generation() -> None:
    assert match_intent('请帮我写测试用例，输出 markdown 表格') == 'test_case_generation'


def test_match_result_analysis_before_test_execution() -> None:
    assert match_intent('分析这段 pytest 失败结果，AssertionError: status code mismatch') == 'result_analysis'


def test_match_test_execution() -> None:
    assert match_intent('执行 pytest 冒烟并分析失败原因') == 'test_execution'
