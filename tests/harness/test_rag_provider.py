from __future__ import annotations

import pytest

from harness.application.source import (
    SourceBundle,
    SourceCompleteness,
    SourceDocument,
    SourceIngestionLimits,
)
from harness.infrastructure.rag.provider import RagProviderConfig, RagRetriever


class Sources:
    def load_source_bundle(self, _workspace: str, _run_id: str) -> SourceBundle:
        return SourceBundle(
            parser_version="test",
            limits=SourceIngestionLimits(),
            documents=(
                SourceDocument(
                    path="sources/rules.md",
                    raw_sha256="sha256:" + "1" * 64,
                    parsed_sha256="sha256:" + "2" * 64,
                    byte_size=45,
                    text="登录连续失败五次后锁定账号。",
                    completeness=SourceCompleteness.COMPLETE,
                ),
            ),
            completeness=SourceCompleteness.COMPLETE,
            bundle_hash="sha256:" + "3" * 64,
        )


def test_local_rag_does_not_require_api_key(monkeypatch) -> None:
    monkeypatch.delenv("RAG_API_KEY", raising=False)
    result = RagRetriever(Sources(), RagProviderConfig()).retrieve(
        "demo", "run-1", "登录失败锁定", 2
    )

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
        RagRetriever(Sources(), config).retrieve("demo", "run-1", "登录", 1)
