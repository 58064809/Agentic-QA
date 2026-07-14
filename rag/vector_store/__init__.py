"""向量存储与相似度搜索。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

try:
    import faiss
except ImportError:
    faiss = None  # type: ignore[assignment]


def _normalize_rows(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


class MemoryVectorStore:
    """基于 NumPy 的轻量向量存储。

    用于本地开发、测试或 FAISS 不可用时的 fallback。索引以 JSON 持久化，
    可读性优先，适合当前知识库规模。
    """

    def __init__(
        self,
        dimensions: int = 1536,
        *,
        metric: str = "cosine",
        index_path: str | Path | None = None,
    ) -> None:
        self.dimensions = dimensions
        self.metric = metric
        self.vectors = np.empty((0, dimensions), dtype=np.float32)
        self.metadata: list[dict[str, Any]] = []
        if index_path:
            self._load_index(Path(index_path))

    def add(self, vectors: list[list[float]], metadata: list[dict[str, Any]]) -> None:
        if not vectors:
            return
        vectors_np = np.array(vectors, dtype=np.float32)
        if vectors_np.ndim != 2 or vectors_np.shape[1] != self.dimensions:
            raise ValueError(f"向量维度不匹配，期望 {self.dimensions}，实际 {vectors_np.shape}")
        if self.metric == "cosine":
            vectors_np = _normalize_rows(vectors_np)
        self.vectors = np.vstack([self.vectors, vectors_np])
        self.metadata.extend(metadata)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
    ) -> list[tuple[dict[str, Any], float]]:
        if self.size == 0:
            return []
        query_np = np.array([query_vector], dtype=np.float32)
        if query_np.shape[1] != self.dimensions:
            raise ValueError(
                f"查询向量维度不匹配，期望 {self.dimensions}，实际 {query_np.shape[1]}"
            )
        if self.metric == "cosine":
            query_np = _normalize_rows(query_np)
            scores = self.vectors @ query_np[0]
            order = np.argsort(scores)[::-1]
        else:
            distances = np.linalg.norm(self.vectors - query_np, axis=1)
            scores = -distances
            order = np.argsort(distances)

        results: list[tuple[dict[str, Any], float]] = []
        for idx in order[: min(top_k, self.size)]:
            score = float(scores[idx])
            if self.metric == "cosine":
                score = max(0.0, min(1.0, (score + 1.0) / 2.0))
            results.append((self.metadata[int(idx)], score))
        return results

    @property
    def size(self) -> int:
        return len(self.metadata)

    def save(self, directory: str | Path) -> None:
        save_dir = Path(directory)
        save_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "dimensions": self.dimensions,
            "metric": self.metric,
            "vectors": self.vectors.tolist(),
            "metadata": self.metadata,
        }
        (save_dir / "memory_index.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_index(self, directory: Path) -> None:
        path = directory / "memory_index.json"
        if not path.is_file():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.dimensions = int(payload.get("dimensions", self.dimensions))
        self.metric = payload.get("metric", self.metric)
        self.vectors = np.array(payload.get("vectors", []), dtype=np.float32)
        if self.vectors.size == 0:
            self.vectors = np.empty((0, self.dimensions), dtype=np.float32)
        self.metadata = list(payload.get("metadata", []))

    def clear(self) -> None:
        self.vectors = np.empty((0, self.dimensions), dtype=np.float32)
        self.metadata = []


class FaissVectorStore:
    """基于 FAISS CPU 的向量存储。

    支持：
    - L2 距离 / 内积（余弦归一化后内积等价于余弦相似度）
    - 添加向量 + 元数据
    - TopK 搜索
    - 持久化到磁盘
    """

    def __init__(
        self,
        dimensions: int = 1536,
        *,
        metric: str = "cosine",
        index_path: str | Path | None = None,
    ) -> None:
        if faiss is None:
            raise RuntimeError("faiss-cpu 未安装，无法使用 FAISS Vector Store。")

        self.dimensions = dimensions
        self.metric = metric

        if index_path:
            loaded = self._load_index(Path(index_path))
            if loaded is not None:
                self.index, self.metadata = loaded
                return

        # 创建新索引
        if metric == "cosine":
            # 内积 + 向量归一化 = 余弦相似度
            self.index = faiss.IndexFlatIP(dimensions)
        else:
            self.index = faiss.IndexFlatL2(dimensions)

        self.metadata: list[dict[str, Any]] = []

    def add(self, vectors: list[list[float]], metadata: list[dict[str, Any]]) -> None:
        """批量添加向量及对应元数据。"""
        if not vectors:
            return

        vectors_np = np.array(vectors, dtype=np.float32)
        if vectors_np.ndim != 2 or vectors_np.shape[1] != self.dimensions:
            raise ValueError(f"向量维度不匹配，期望 {self.dimensions}，实际 {vectors_np.shape}")
        if self.metric == "cosine":
            faiss.normalize_L2(vectors_np)

        self.index.add(vectors_np)
        self.metadata.extend(metadata)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
    ) -> list[tuple[dict[str, Any], float]]:
        """搜索 TopK 最相似的向量。

        返回 [(metadata, score), ...] ，score 范围 [0,1]（余弦）或距离（L2）。
        """
        if self.index.ntotal == 0:
            return []

        query_np = np.array([query_vector], dtype=np.float32)
        if query_np.shape[1] != self.dimensions:
            raise ValueError(
                f"查询向量维度不匹配，期望 {self.dimensions}，实际 {query_np.shape[1]}"
            )
        if self.metric == "cosine":
            faiss.normalize_L2(query_np)

        actual_k = min(top_k, self.index.ntotal)
        distances, indices = self.index.search(query_np, actual_k)

        results: list[tuple[dict[str, Any], float]] = []
        for i, idx in enumerate(indices[0]):
            if idx == -1 or idx >= len(self.metadata):
                continue
            score = float(distances[0][i])
            if self.metric == "cosine":
                # 内积转换为 [0,1] 余弦相似度
                score = max(0.0, min(1.0, (score + 1.0) / 2.0))
            results.append((self.metadata[idx], score))

        return results

    @property
    def size(self) -> int:
        return self.index.ntotal

    def save(self, directory: str | Path) -> None:
        """将索引和元数据持久化到磁盘。"""
        save_dir = Path(directory)
        save_dir.mkdir(parents=True, exist_ok=True)

        index_path = save_dir / "index.faiss"
        metadata_path = save_dir / "metadata.json"

        faiss.write_index(self.index, str(index_path))
        metadata_path.write_text(
            json.dumps(self.metadata, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_index(self, directory: Path) -> tuple[Any, list[dict[str, Any]]] | None:
        """从磁盘加载索引和元数据。"""
        index_path = directory / "index.faiss"
        metadata_path = directory / "metadata.json"

        if not index_path.is_file() or not metadata_path.is_file():
            return None

        index = faiss.read_index(str(index_path))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        return index, metadata

    def clear(self) -> None:
        """清空索引和元数据。"""
        if self.metric == "cosine":
            self.index = faiss.IndexFlatIP(self.dimensions)
        else:
            self.index = faiss.IndexFlatL2(self.dimensions)
        self.metadata = []
