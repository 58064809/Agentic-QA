from __future__ import annotations

import pytest

from harness.infrastructure.rag.provider import RagProviderConfig, RagRetriever


class Sources:
    def source_texts(self, _workspace: str, limit: int = 100_000):
        assert limit == 100_000
        return [("sources/rules.md", "登录连续失败五次后锁定账号")]


def test_local_rag_does_not_require_api_key(monkeypatch) -> None:
    monkeypatch.delenv("RAG_API_KEY", raising=False)
    result = RagRetriever(Sources(), RagProviderConfig()).retrieve("demo", "登录失败锁定", 2)

    assert result["provider"] == "local-lexical"
    assert result["chunks"][0]["source"] == "sources/rules.md"


def test_rag_config_uses_mapped_api_key_variable_name(monkeypatch) -> None:
    monkeypatch.setenv("AGENTIC_QA_RAG_API_KEY_ENV", "PROJECT_RAG_TOKEN")

    config = RagProviderConfig.from_workspace({"provider": "openai-compatible"})

    assert config.api_key_env == "PROJECT_RAG_TOKEN"


def test_remote_rag_fails_without_named_api_key(monkeypatch) -> None:
    monkeypatch.delenv("PROJECT_RAG_TOKEN", raising=False)
    config = RagProviderConfig(
        provider="openai-compatible",
        api_key_env="PROJECT_RAG_TOKEN",
    )

    with pytest.raises(RuntimeError, match="PROJECT_RAG_TOKEN"):
        RagRetriever(Sources(), config).retrieve("demo", "登录", 1)
