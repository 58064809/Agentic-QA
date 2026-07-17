from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel

from harness.contracts import PlanTask, TaskRequest
from harness.model import (
    DEFAULT_DEEPSEEK_BASE_URL,
    ModelConfig,
    ModelPolicy,
    ModelRoute,
    OpenAICompatibleModelGateway,
)


class ExampleOutput(BaseModel):
    value: str


def test_deepseek_key_enables_default_v4_routing(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-a-real-key")
    monkeypatch.delenv("AGENTIC_QA_MODEL", raising=False)
    monkeypatch.delenv("AGENTIC_QA_MODEL_FLASH", raising=False)
    monkeypatch.delenv("AGENTIC_QA_MODEL_PRO", raising=False)
    monkeypatch.delenv("AGENTIC_QA_MODEL_API_KEY_ENV", raising=False)
    monkeypatch.delenv("AGENTIC_QA_MODEL_BASE_URL", raising=False)

    config = ModelConfig.from_env()

    assert config is not None
    assert config.api_key_env == "DEEPSEEK_API_KEY"
    assert config.base_url == DEFAULT_DEEPSEEK_BASE_URL
    assert config.flash_model == "deepseek-v4-flash"
    assert config.pro_model == "deepseek-v4-pro"


def test_single_model_override_pins_both_tiers(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-a-real-key")
    monkeypatch.setenv("AGENTIC_QA_MODEL", "deepseek-v4-flash")

    config = ModelConfig.from_env()

    assert config is not None
    assert config.flash_model == "deepseek-v4-flash"
    assert config.pro_model == "deepseek-v4-flash"


def test_policy_uses_pro_only_for_complex_plans_and_specialists() -> None:
    policy = ModelPolicy()

    routine = policy.for_planner(TaskRequest(workspace="demo", goal="design tests"))
    complex_route = policy.for_planner(
        TaskRequest(
            workspace="demo",
            goal="triage failures",
            expected_artifacts=["failure_analysis"],
        )
    )
    analyst = policy.for_task(
        PlanTask(id="analysis", objective="analyze", agent="requirement_analyst")
    )
    triager = policy.for_task(PlanTask(id="triage", objective="triage", agent="failure_triager"))

    assert (routine.tier, routine.thinking) == ("flash", "enabled")
    assert (complex_route.tier, complex_route.reasoning_effort) == ("pro", "max")
    assert (analyst.tier, analyst.thinking) == ("flash", "disabled")
    assert (triager.tier, triager.thinking) == ("pro", "enabled")


def test_deepseek_gateway_uses_json_object_and_thinking_parameters(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-a-real-key")
    gateway = OpenAICompatibleModelGateway(ModelConfig())
    captured: dict = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"value":"ok"}'))],
        )

    gateway._client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    route = ModelRoute(
        tier="pro",
        thinking="enabled",
        reasoning_effort="max",
        purpose="test",
    )

    result = gateway.structured(
        system="Return json.",
        prompt="test",
        response_model=ExampleOutput,
        route=route,
    )

    assert result.value == "ok"
    assert captured["model"] == "deepseek-v4-pro"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["extra_body"] == {"thinking": {"type": "enabled"}}
    assert captured["reasoning_effort"] == "max"
    assert "JSON Schema" in captured["messages"][0]["content"]
    assert gateway.route_history == [
        {
            "tier": "pro",
            "thinking": "enabled",
            "purpose": "test",
            "reasoning_effort": "max",
            "model": "deepseek-v4-pro",
        }
    ]
