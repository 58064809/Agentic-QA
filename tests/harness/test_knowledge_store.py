from __future__ import annotations

import pytest

from harness.application.source import SourceCompleteness, SourceDocument
from harness.domain.schemas.knowledge import KnowledgeTrust
from harness.infrastructure.knowledge_service import _artifact_trust, _source_trust
from harness.infrastructure.knowledge_store import (
    DeterministicEmbeddingProvider,
    SourceAwareChunker,
)


def test_source_aware_chunker_keeps_table_and_rule_blocks_atomic() -> None:
    text = """# Rules

| Rule | Result |
|---|---|
| R-1 | allow |
| R-2 | deny |

# Constraints

- amount must be positive
- role must be approver
"""
    chunks = SourceAwareChunker(500).chunk("requirements.md", text)
    assert [item.structure_kind for item in chunks] == ["table", "list_or_rule_block"]
    assert "| R-1 | allow |" in chunks[0].content
    assert "- amount must be positive" in chunks[1].content


def test_large_table_repeats_header_without_splitting_rows() -> None:
    rows = "\n".join(f"| R-{index:03d} | {'x' * 60} |" for index in range(12))
    chunks = SourceAwareChunker(500).chunk(
        "requirements.md", f"# Rules\n\n| Rule | Result |\n|---|---|\n{rows}"
    )
    assert len(chunks) > 1
    assert all("| Rule | Result |" in item.content for item in chunks)
    assert all(item.structure_kind == "table" for item in chunks)


def test_chunker_fails_closed_for_atomic_oversize_and_skips_secrets() -> None:
    chunker = SourceAwareChunker(500)
    with pytest.raises(ValueError, match="exceeds"):
        chunker.chunk("requirements.md", "# Rule\n\n" + "x" * 600)
    assert chunker.chunk("secret.md", "Authorization: Bearer abcdefghijklmnop") == []


def test_deterministic_embedding_profile_is_fixed_and_repeatable() -> None:
    provider = DeterministicEmbeddingProvider()
    first = provider.embed(["支付 payment retry"])[0]
    second = provider.embed(["支付 payment retry"])[0]
    assert provider.dimensions == 1536
    assert first == second
    assert len(first) == 1536


def test_source_and_artifact_trust_are_classified_independently() -> None:
    def document(path: str) -> SourceDocument:
        return SourceDocument(
            path=path,
            parsed_sha256="sha256:" + "1" * 64,
            text="safe",
            completeness=SourceCompleteness.COMPLETE,
        )

    assert _source_trust(document("sources/openapi.yml")) == KnowledgeTrust.REVIEWED_CONTRACT
    assert _source_trust(document("sources/readme.md")) == KnowledgeTrust.REFERENCE_ONLY
    assert _artifact_trust("requirement_analysis") == KnowledgeTrust.REVIEWED_REQUIREMENT
    assert _artifact_trust("testcases") == KnowledgeTrust.REVIEWED_TEST_ASSET
    assert _artifact_trust("failure_triage") == KnowledgeTrust.REVIEWED_BUG
