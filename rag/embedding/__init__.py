"""Embedding 适配器 — 使用 OpenAI-compatible API 生成向量。"""

from __future__ import annotations

import numpy as np
from typing import Any

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment]

EMBEDDING_TIMEOUT = 60.0

# 模型 → 维度映射（默认值，实际以 API 返回为准）
KNOWN_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class OpenAIEmbeddingAdapter:
    """使用 OpenAI-compatible API 生成 Embedding。"""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._dimensions = dimensions or KNOWN_DIMENSIONS.get(model, 1536)

        if OpenAI is None:
            raise RuntimeError("openai SDK 未安装，无法使用 Embedding。")

        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=EMBEDDING_TIMEOUT,
            max_retries=1,
        )

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_text(self, text: str) -> list[float]:
        """将单段文本转为向量。"""
        if not text or not text.strip():
            return [0.0] * self._dimensions

        kwargs: dict[str, Any] = {
            "model": self.model,
            "input": text.strip(),
        }
        if self.model in ("text-embedding-3-small", "text-embedding-3-large"):
            kwargs["dimensions"] = self._dimensions

        response = self._client.embeddings.create(**kwargs)
        return response.data[0].embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量将文本转为向量。"""
        if not texts:
            return []

        # 过滤空文本
        valid_texts = [t.strip() for t in texts]
        valid_indices = [i for i, t in enumerate(valid_texts) if t]
        non_empty_texts = [valid_texts[i] for i in valid_indices]

        if not non_empty_texts:
            return [[0.0] * self._dimensions for _ in texts]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "input": non_empty_texts,
        }
        if self.model in ("text-embedding-3-small", "text-embedding-3-large"):
            kwargs["dimensions"] = self._dimensions

        response = self._client.embeddings.create(**kwargs)

        # 重建完整结果（空文本位置填充零向量）
        result_map: dict[int, list[float]] = {}
        for data_item in response.data:
            result_map[valid_indices[data_item.index]] = data_item.embedding

        return [
            result_map.get(i, [0.0] * self._dimensions)
            for i in range(len(texts))
        ]

    def compute_similarity(
        self, embedding_a: list[float], embedding_b: list[float],
    ) -> float:
        """计算两个向量的余弦相似度。"""
        a = np.array(embedding_a, dtype=np.float32)
        b = np.array(embedding_b, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
