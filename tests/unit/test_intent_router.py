from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.llm.config import OpenAICompatibleConfig  # noqa: E402
from runtime.llm.intent_router import route_intent  # noqa: E402
from runtime.llm.openai_compatible import OpenAICompatibleAdapter  # noqa: E402


def test_route_intent_without_api_key_falls_back_to_plain_natural_language(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    route = route_intent(
        "帮我分析 prd/5月第二周运营活动核心需求-review 并生成测试用例",
        OpenAICompatibleConfig.from_env(),
    )

    assert route.is_valid
    assert route.intent == "analysis_and_testcases"
    assert route.prd_path == "prd/5月第二周运营活动核心需求-review"
    assert "降级" in route.summary


def test_route_intent_llm_failure_falls_back(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-secret")

    def raise_timeout(self, prompt):
        raise TimeoutError("mock timeout")

    monkeypatch.setattr(OpenAICompatibleAdapter, "generate_text", raise_timeout)

    route = route_intent(
        "帮我分析 prd/demo-requirement 并生成测试用例",
        OpenAICompatibleConfig.from_env(),
    )

    assert route.is_valid
    assert route.intent == "analysis_and_testcases"
    assert route.prd_path == "prd/demo-requirement"
    assert "LLM 路由调用失败" in route.summary


def test_route_intent_rag_automation_case_without_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    route = route_intent(
        "基于 prd/demo-requirement 用 RAG 生成 YAML 接口自动化用例",
        OpenAICompatibleConfig.from_env(),
    )

    assert route.is_valid
    assert route.intent == "rag_automation_case_generation"
    assert route.prd_path == "prd/demo-requirement"
