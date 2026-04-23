from runtime.intent_matcher import match_intent


def test_match_requirement_analysis() -> None:
    assert match_intent("帮我分析需求，看看 PRD 和原型") == "requirement_analysis"


def test_match_requirement_analysis_with_module_name_between_words() -> None:
    assert match_intent("帮我分析缴纳保证金需求，结合 PRD 和原型图") == "requirement_analysis"


def test_match_test_case_generation() -> None:
    assert match_intent("根据需求生成测试用例，输出 markdown 表格") == "test_case_generation"


def test_match_script_generation() -> None:
    assert match_intent("根据 PRD 生成 pytest 脚本") == "script_generation"


def test_match_result_analysis_before_test_execution() -> None:
    assert match_intent("分析 pytest 失败结果，traceback 里有 AssertionError") == "result_analysis"


def test_match_log_analysis() -> None:
    assert match_intent("帮我查日志，看看 error 和 traceId") == "log_analysis"
