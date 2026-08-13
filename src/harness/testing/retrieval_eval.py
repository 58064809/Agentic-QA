from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from harness.domain.schemas.knowledge import RetrievalEvalMetrics
from harness.infrastructure.knowledge_store import (
    DeterministicEmbeddingProvider,
    SourceAwareChunker,
)

TOKEN = re.compile(r"[a-z0-9_\-]+|[\u4e00-\u9fff]{2,}", re.I)


def score_retrieval_golden(records: Iterable[dict[str, Any]]) -> RetrievalEvalMetrics:
    records = list(records)
    if not records:
        raise ValueError("retrieval golden requires at least one query")
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    source_hits = 0
    wrong_sources = 0
    returned = 0
    superseded = 0
    cross_workspace = 0
    embedding_mismatch = 0
    wrong_trust = 0
    superseded_current_fact = 0
    for record in records:
        expected_chunks = set(record.get("expected_chunk_ids") or [])
        expected_sources = set(record.get("expected_sources") or [])
        workspace_id = record.get("workspace_id")
        results = list(record.get("results") or [])[:10]
        found = [item.get("chunk_id") for item in results]
        expected_keys = expected_chunks or expected_sources
        found_keys = found if expected_chunks else [item.get("source_identity") for item in results]
        recalls.append(len(expected_keys & set(found_keys)) / len(expected_keys))
        ranks = [index for index, key in enumerate(found_keys, 1) if key in expected_keys]
        reciprocal_ranks.append(1 / min(ranks) if ranks else 0.0)
        sources = {item.get("source_identity") for item in results}
        source_hits += bool(expected_sources & sources)
        wrong_sources += sum(
            bool(expected_sources) and item.get("source_identity") not in expected_sources
            for item in results
        )
        returned += len(results)
        superseded += sum(item.get("freshness") in {"superseded", "deprecated"} for item in results)
        cross_workspace += sum(item.get("workspace_id") != workspace_id for item in results)
        expected_embedding = record.get("expected_embedding_index_identity")
        allowed_trust = set(record.get("allowed_trust") or [])
        embedding_mismatch += sum(
            bool(expected_embedding) and item.get("embedding_index_identity") != expected_embedding
            for item in results
        )
        wrong_trust += sum(
            bool(allowed_trust) and item.get("trust") not in allowed_trust for item in results
        )
        superseded_current_fact += sum(
            record.get("fact_scope") == "current"
            and item.get("freshness") in {"superseded", "deprecated"}
            for item in results
        )
    count = len(records)
    recall = sum(recalls) / count
    mrr = sum(reciprocal_ranks) / count
    hit_rate = source_hits / count
    wrong_rate = wrong_sources / returned if returned else 0.0
    passed = (
        recall >= 0.90
        and mrr >= 0.80
        and hit_rate >= 0.95
        and wrong_rate <= 0.05
        and superseded == 0
        and cross_workspace == 0
        and embedding_mismatch == 0
        and wrong_trust == 0
        and superseded_current_fact == 0
    )
    return RetrievalEvalMetrics(
        query_count=count,
        recall_at_10=recall,
        mrr=mrr,
        source_hit_rate=hit_rate,
        wrong_source_rate=wrong_rate,
        superseded_leakage=superseded,
        cross_workspace_leakage=cross_workspace,
        embedding_space_mismatch_leakage=embedding_mismatch,
        wrong_trust_promotion=wrong_trust,
        superseded_current_fact_leakage=superseded_current_fact,
        passed=passed,
    )


def run_retrieval_golden(root: Path | None = None) -> dict[str, Any]:
    path = (root or Path.cwd()) / "evals" / "retrieval" / "golden.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    provider = DeterministicEmbeddingProvider()
    chunker = SourceAwareChunker()
    records: list[dict[str, Any]] = []
    for case in payload["cases"]:
        chunks = [
            (source, draft.ordinal, draft.content)
            for source, content in case["documents"].items()
            for draft in chunker.chunk(source, content)
        ]
        query = case["query"]
        vectors = provider.embed([query, *[item[2] for item in chunks]])
        query_terms = _terms(query)
        lexical = sorted(
            (
                (len(query_terms & _terms(content)), source, ordinal)
                for source, ordinal, content in chunks
            ),
            key=lambda item: (-item[0], item[1], item[2]),
        )
        lexical_rank = {
            (source, ordinal): rank
            for rank, (score, source, ordinal) in enumerate(lexical, 1)
            if score
        }
        semantic = sorted(
            (
                (_cosine(vectors[0], vector), source, ordinal)
                for (source, ordinal, _), vector in zip(chunks, vectors[1:], strict=True)
            ),
            key=lambda item: (-item[0], item[1], item[2]),
        )
        semantic_rank = {
            (source, ordinal): rank for rank, (_, source, ordinal) in enumerate(semantic, 1)
        }
        ranked = sorted(
            chunks,
            key=lambda item: (
                -(
                    (1 / (60 + lexical_rank[(item[0], item[1])]))
                    if (item[0], item[1]) in lexical_rank
                    else 0
                )
                - 1 / (60 + semantic_rank[(item[0], item[1])]),
                item[0],
                item[1],
            ),
        )[: case.get("max_chunks", 1)]
        records.append(
            {
                **case,
                "results": [
                    {
                        "chunk_id": "CHUNK-"
                        + hashlib.sha256(f"{source}:{ordinal}:{content}".encode()).hexdigest()[:16],
                        "source_identity": source,
                        "workspace_id": case["workspace_id"],
                        "freshness": "current",
                    }
                    for source, ordinal, content in ranked
                ],
            }
        )
    metrics = score_retrieval_golden(records)
    return metrics.model_dump(mode="json")


def _terms(text: str) -> set[str]:
    return {item.casefold() for item in TOKEN.findall(text)}


def _cosine(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    if denominator == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator
