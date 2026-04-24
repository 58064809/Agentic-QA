from runtime.intent_matcher import match_intent
from runtime.intent_matcher import match_intent_details


def test_match_requirement_analysis() -> None:
    assert match_intent("帮我分析需求，看看 PRD 和原型") == "requirement_analysis"


def test_match_requirement_analysis_with_synonym_phrase() -> None:
    assert match_intent("帮我 review requirement，顺便梳理一下原型流程") == "requirement_analysis"


def test_match_test_case_generation() -> None:
    assert match_intent("根据需求生成测试用例，输出 markdown 表格") == "test_case_generation"


def test_match_script_generation() -> None:
    assert match_intent("根据 PRD 生成 pytest 脚本") == "script_generation"


def test_match_result_analysis_before_test_execution() -> None:
    assert match_intent("分析 pytest 失败结果，traceback 里有 AssertionError") == "result_analysis"


def test_match_log_analysis() -> None:
    assert match_intent("帮我查日志，看看 error 和 traceId") == "log_analysis"


def test_negation_avoids_test_execution_intent() -> None:
    match = match_intent_details("不要执行 pytest，只分析失败结果和 traceback")

    assert match is not None
    assert match.name == "result_analysis"
    assert "不要执行" not in match.matched_keywords


def test_ambiguous_request_requires_clarification() -> None:
    match = match_intent_details("帮我处理一下 pytest")

    assert match is not None
    assert match.needs_clarification is True
    assert match.reason in {"top_intent_score_too_low", "matched_signals_too_sparse", "top_candidates_too_close"}
    assert match.alternatives


def test_workflow_combo_wins_when_generate_cases_and_run() -> None:
    match = match_intent_details("分析需求后生成测试用例并执行 pytest")

    assert match is not None
    assert match.name == "test_workflow_execution"
    assert match.needs_clarification is False
    assert match.confidence >= 0.7
