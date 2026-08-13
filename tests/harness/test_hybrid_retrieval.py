from __future__ import annotations

from pathlib import Path

import pytest

from harness.domain.schemas.knowledge import (
    KnowledgeFreshness,
    KnowledgeTrust,
    RetrievalFilters,
    RetrievalQuery,
)
from harness.infrastructure.rag.provider import ModelReranker, PostgresHybridRetriever


def test_hybrid_filter_sql_covers_every_public_filter() -> None:
    query = RetrievalQuery(
        workspace_id="demo",
        run_id="run-1",
        query="approval",
        purpose="impact",
        filters=RetrievalFilters(
            source_types=["requirement"],
            document_versions=[2],
            business_modules=["billing"],
            environments=["qa"],
            freshness=[KnowledgeFreshness.HISTORICAL],
            trust=[KnowledgeTrust.REVIEWED_REQUIREMENT],
        ),
    )
    sql, parameters = PostgresHybridRetriever._metadata_filter(query)
    assert all(
        column in sql
        for column in (
            "d.document_type",
            "v.version_number",
            "d.business_module",
            "d.environment",
            "v.freshness",
            "v.trust",
        )
    )
    assert parameters == [
        ["requirement"],
        [2],
        ["billing"],
        ["qa"],
        ["historical"],
        ["reviewed_requirement"],
    ]


class _InvalidRerankerModel:
    def structured(self, **_kwargs):
        class Result:
            chunk_ids = ["CHUNK-NEW"]

        return Result()


def test_model_reranker_cannot_add_knowledge() -> None:
    with pytest.raises(ValueError, match="exactly the provided"):
        ModelReranker(_InvalidRerankerModel()).rerank(
            "query", [{"chunk_id": "CHUNK-1", "content": "untrusted"}]
        )


def test_retrieval_purpose_rejects_trust_escalation() -> None:
    with pytest.raises(ValueError, match="forbids trust"):
        RetrievalQuery(
            workspace_id="demo",
            run_id="run-1",
            query="coupon rule",
            purpose="requirement",
            filters=RetrievalFilters(trust=[KnowledgeTrust.REVIEWED_BUG]),
        )
    query = RetrievalQuery(
        workspace_id="demo",
        run_id="run-1",
        query="coupon rule",
        purpose="risk",
    )
    assert KnowledgeTrust.REVIEWED_BUG in query.filters.trust
    assert KnowledgeTrust.REVIEWED_REQUIREMENT not in query.filters.trust


def test_vector_query_isolated_to_current_embedding_identity() -> None:
    source = Path("src/harness/infrastructure/rag/provider.py").read_text(encoding="utf-8")
    assert "ce.provider=%s AND ce.model=%s AND ce.dimensions=%s" in source
    assert "embedding_index_identity" in source
