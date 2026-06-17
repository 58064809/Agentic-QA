"""Embedding 适配器。

默认支持 OpenAI-compatible API，也提供本地哈希向量实现，保证 RAG 在无外部
Embedding 服务时仍可进行确定性检索。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Protocol

import numpy as np

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment]

EMBEDDING_TIMEOUT = 60.0
OPENAI_COMPATIBLE_BATCH_SIZE = 10
DIMENSION_PARAMETER_MODELS = {
    "text-embedding-3-small",
    "text-embedding-3-large",
    "text-embedding-v4",
}

# 模型 → 维度映射（默认值，实际以 API 返回为准）
KNOWN_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class EmbeddingAdapter(Protocol):
    """Embedding 适配器协议。"""

    @property
    def dimensions(self) -> int: ...

    def embed_text(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in TOKEN_RE.findall(text.lower()):
        tokens.append(token)
        if CJK_RE.search(token):
            chars = [char for char in token if CJK_RE.match(char)]
            tokens.extend(chars)
            for size in (2, 3):
                tokens.extend(
                    "".join(chars[index : index + size])
                    for index in range(0, max(0, len(chars) - size + 1))
                )
    return tokens


class LocalHashEmbeddingAdapter:
    """基于 token 哈希的本地 Embedding。

    它不是语义向量模型，但对 QA 方法、规则、模板类文档的关键词召回足够稳定，
    并且不需要网络、API Key 或额外模型文件。
    """

    def __init__(self, dimensions: int = 384) -> None:
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_text(self, text: str) -> list[float]:
        vector = np.zeros(self._dimensions, dtype=np.float32)
        if not text or not text.strip():
            return vector.tolist()

        for token in _tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], byteorder="big") % self._dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
        return vector.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(text) for text in texts]

    def compute_similarity(self, embedding_a: list[float], embedding_b: list[float]) -> float:
        return compute_similarity(embedding_a, embedding_b)


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
        if self.model in DIMENSION_PARAMETER_MODELS:
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

        result_map: dict[int, list[float]] = {}
        for start in range(0, len(non_empty_texts), OPENAI_COMPATIBLE_BATCH_SIZE):
            batch_texts = non_empty_texts[start : start + OPENAI_COMPATIBLE_BATCH_SIZE]
            kwargs: dict[str, Any] = {
                "model": self.model,
                "input": batch_texts,
            }
            if self.model in DIMENSION_PARAMETER_MODELS:
                kwargs["dimensions"] = self._dimensions

            response = self._client.embeddings.create(**kwargs)

            for data_item in response.data:
                original_index = valid_indices[start + data_item.index]
                result_map[original_index] = data_item.embedding

        return [result_map.get(i, [0.0] * self._dimensions) for i in range(len(texts))]

    def compute_similarity(self, embedding_a: list[float], embedding_b: list[float]) -> float:
        return compute_similarity(embedding_a, embedding_b)


def compute_similarity(embedding_a: list[float], embedding_b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    a = np.array(embedding_a, dtype=np.float32)
    b = np.array(embedding_b, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))
