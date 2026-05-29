from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.llm import openai_compatible  # noqa: E402
from runtime.llm.config import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    OpenAICompatibleConfig,
)
from runtime.llm.openai_compatible import OpenAICompatibleAdapter  # noqa: E402
from runtime.llm.prompt_builder import build_requirement_analysis_prompt  # noqa: E402


def test_openai_compatible_config_defaults_without_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    config = OpenAICompatibleConfig.from_env()
    metadata = config.to_metadata(enabled=True)

    assert config.api_key is None
    assert config.base_url == DEFAULT_BASE_URL
    assert config.model == DEFAULT_MODEL
    assert metadata["enabled"] is True
    assert "api_key" not in metadata


def test_openai_compatible_config_reads_env_without_serializing_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-secret")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("DEEPSEEK_ENABLE_CHAT_FALLBACK", "false")
    monkeypatch.setenv("DEEPSEEK_MAX_INPUT_CHARS", "8000")

    config = OpenAICompatibleConfig.from_env()
    metadata = config.to_metadata(enabled=True)

    assert config.has_api_key
    assert config.api_key == "local-secret"
    assert metadata == {
        "enabled": True,
        "used": False,
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "chat_fallback_enabled": False,
        "max_input_chars": 8000,
        "calls": 0,
        "errors": [],
    }


def test_prompt_builder_truncates_large_context():
    loaded_files = {
        "prd/demo-requirement/requirement.md": "a" * 200,
        "rules/requirement-analysis-rules.md": "b" * 200,
        "skills/requirement-decomposition-skill.md": "c" * 200,
        "skills/business-rule-extraction-skill.md": "d" * 200,
        "prompts/requirement-analysis-prompt.md": "e" * 200,
    }

    result = build_requirement_analysis_prompt(
        loaded_files,
        prd_prefix="prd/demo-requirement",
        max_input_chars=120,
    )

    assert len(result.prompt) < 2500  # 基础指令+CoT+自检约1300，截断后总长度应合理
    assert result.warnings == ["LLM Prompt 输入超过 120 字符，已截断。"]


def test_openai_adapter_prefers_responses_create(monkeypatch):
    calls = {"responses": 0, "chat": 0}

    class FakeResponses:
        def create(self, **kwargs):
            calls["responses"] += 1
            assert kwargs["model"] == "demo-model"
            assert kwargs["input"] == f"{openai_compatible.SYSTEM_PROMPT}\n\nprompt text"
            return SimpleNamespace(output_text="responses markdown")

    class FakeChatCompletions:
        def create(self, **kwargs):
            calls["chat"] += 1
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="chat markdown"))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "local-secret"
            assert kwargs["base_url"] == "https://example.test/v1"
            self.responses = FakeResponses()
            self.chat = SimpleNamespace(completions=FakeChatCompletions())

    monkeypatch.setattr(openai_compatible, "OpenAI", FakeOpenAI)
    config = OpenAICompatibleConfig(
        api_key="local-secret",
        base_url="https://example.test/v1",
        model="demo-model",
    )

    content = OpenAICompatibleAdapter(config).generate_text("prompt text")

    assert content == "responses markdown"
    assert calls == {"responses": 1, "chat": 0}


def test_openai_adapter_falls_back_to_chat_completions(monkeypatch):
    calls = {"responses": 0, "chat": 0}

    class FakeResponses:
        def create(self, **kwargs):
            calls["responses"] += 1
            raise AttributeError("responses not supported")

    class FakeChatCompletions:
        def create(self, **kwargs):
            calls["chat"] += 1
            assert kwargs["messages"][1]["content"] == "prompt text"
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="chat markdown"))]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()
            self.chat = SimpleNamespace(completions=FakeChatCompletions())

    monkeypatch.setattr(openai_compatible, "OpenAI", FakeOpenAI)
    config = OpenAICompatibleConfig(
        api_key="local-secret",
        model="demo-model",
        enable_chat_fallback=True,
    )

    content = OpenAICompatibleAdapter(config).generate_text("prompt text")

    assert content == "chat markdown"
    assert calls == {"responses": 1, "chat": 1}
