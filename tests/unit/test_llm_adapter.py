from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.llm.config import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    OpenAICompatibleConfig,
)
from runtime.llm.prompt_builder import build_requirement_analysis_prompt  # noqa: E402


def test_openai_compatible_config_defaults_without_api_key(monkeypatch):
    monkeypatch.delenv("FREEMODEL_API_KEY", raising=False)
    monkeypatch.delenv("FREEMODEL_BASE_URL", raising=False)
    monkeypatch.delenv("FREEMODEL_MODEL", raising=False)

    config = OpenAICompatibleConfig.from_env()
    metadata = config.to_metadata(enabled=True)

    assert config.api_key is None
    assert config.base_url == DEFAULT_BASE_URL
    assert config.model == DEFAULT_MODEL
    assert metadata["enabled"] is True
    assert "api_key" not in metadata


def test_openai_compatible_config_reads_env_without_serializing_key(monkeypatch):
    monkeypatch.setenv("FREEMODEL_API_KEY", "local-secret")
    monkeypatch.setenv("FREEMODEL_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("FREEMODEL_MODEL", "demo-model")

    config = OpenAICompatibleConfig.from_env()
    metadata = config.to_metadata(enabled=True)

    assert config.has_api_key
    assert config.api_key == "local-secret"
    assert metadata == {
        "enabled": True,
        "used": False,
        "provider": "openai_compatible",
        "base_url": "https://example.test/v1",
        "model": "demo-model",
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

    assert len(result.prompt) < 1200
    assert result.warnings == ["LLM Prompt 输入超过 120 字符，已截断。"]
