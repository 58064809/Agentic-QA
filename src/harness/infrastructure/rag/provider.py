from __future__ import annotations

import math
import os
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

TOKEN = re.compile(r"[\w\u4e00-\u9fff-]{2,}")


class SourceRepository(Protocol):
    def source_texts(self, workspace: str, limit: int = 100_000) -> list[tuple[str, str]]: ...


class RagProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agentic-qa.harness.rag-provider.v2"] = (
        "agentic-qa.harness.rag-provider.v2"
    )
    provider: Literal["local-lexical", "openai-compatible"] = "local-lexical"
    api_key_env: str = "RAG_API_KEY"
    base_url_env: str = "AGENTIC_QA_RAG_BASE_URL"
    model: str = "text-embedding-3-small"
    chunk_size: int = Field(default=1200, ge=200, le=4000)
    chunk_overlap: int = Field(default=400, ge=0, le=1000)

    @classmethod
    def from_workspace(cls, raw: object) -> RagProviderConfig:
        payload = dict(raw) if isinstance(raw, dict) else {}
        payload.setdefault(
            "api_key_env",
            os.getenv("AGENTIC_QA_RAG_API_KEY_ENV", "RAG_API_KEY").strip() or "RAG_API_KEY",
        )
        return cls.model_validate(payload)


class RagRetriever:
    def __init__(self, sources: SourceRepository, config: RagProviderConfig) -> None:
        self.sources = sources
        self.config = config

    def retrieve(self, workspace: str, query: str, max_chunks: int) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("rag.retrieve requires query")
        chunks = self._chunks(workspace)
        if self.config.provider == "openai-compatible":
            selected = self._semantic(query, chunks, max_chunks)
        else:
            selected = self._lexical(query, chunks, max_chunks)
        return {
            "query": query,
            "provider": self.config.provider,
            "chunks": [
                {
                    "source": source,
                    "chunk_id": f"{source}#chunk-{index}",
                    "selection_reason": reason,
                    "content": content,
                }
                for source, index, content, reason in selected
            ],
        }

    def _chunks(self, workspace: str) -> list[tuple[str, int, str]]:
        step = max(self.config.chunk_size - self.config.chunk_overlap, 1)
        chunks: list[tuple[str, int, str]] = []
        for source, content in self.sources.source_texts(workspace):
            for index, start in enumerate(range(0, len(content), step)):
                chunks.append((source, index, content[start : start + self.config.chunk_size]))
        return chunks

    def _lexical(
        self,
        query: str,
        chunks: list[tuple[str, int, str]],
        max_chunks: int,
    ) -> list[tuple[str, int, str, str]]:
        terms: set[str] = set()
        for token in TOKEN.findall(query):
            lowered = token.lower()
            terms.add(lowered)
            if any("\u4e00" <= char <= "\u9fff" for char in lowered):
                terms.update(lowered[index : index + 2] for index in range(len(lowered) - 1))
        scored = []
        for source, index, content in chunks:
            score = sum(term in content.lower() for term in terms)
            if score:
                scored.append((score, source, index, content))
        return [
            (source, index, content, f"lexical_match:{score}")
            for score, source, index, content in sorted(
                scored, key=lambda item: (-item[0], item[1], item[2])
            )[:max_chunks]
        ]

    def _semantic(
        self,
        query: str,
        chunks: list[tuple[str, int, str]],
        max_chunks: int,
    ) -> list[tuple[str, int, str, str]]:
        api_key = os.getenv(self.config.api_key_env, "").strip()
        if not api_key:
            raise RuntimeError(
                f"RAG API key environment variable is not set: {self.config.api_key_env}"
            )
        base_url = os.getenv(self.config.base_url_env, "").strip() or None
        from openai import OpenAI

        response = OpenAI(api_key=api_key, base_url=base_url).embeddings.create(
            model=self.config.model,
            input=[query, *(content for _, _, content in chunks)],
        )
        vectors = [item.embedding for item in response.data]
        query_vector, chunk_vectors = vectors[0], vectors[1:]
        scored = [
            (_cosine(query_vector, vector), source, index, content)
            for (source, index, content), vector in zip(chunks, chunk_vectors, strict=True)
        ]
        return [
            (source, index, content, f"semantic_cosine:{score:.6f}")
            for score, source, index, content in sorted(
                scored, key=lambda item: (-item[0], item[1], item[2])
            )[:max_chunks]
        ]


def _cosine(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    if denominator == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator
