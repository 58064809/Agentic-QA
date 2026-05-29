"""FAISS Vector Store — 向量存储与相似度搜索。"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import numpy as np

try:
    import faiss
except ImportError:
    faiss = None  # type: ignore[assignment]


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
            raise RuntimeError("faiss-cpu 未安装，无法使用 Vector Store。")

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
        metadata_path = save_dir / "metadata.pkl"

        faiss.write_index(self.index, str(index_path))
        with open(metadata_path, "wb") as f:
            pickle.dump(self.metadata, f)

    def _load_index(self, directory: Path) -> tuple[Any, list[dict[str, Any]]] | None:
        """从磁盘加载索引和元数据。"""
        index_path = directory / "index.faiss"
        metadata_path = directory / "metadata.pkl"

        if not index_path.is_file() or not metadata_path.is_file():
            return None

        index = faiss.read_index(str(index_path))
        with open(metadata_path, "rb") as f:
            metadata: list[dict[str, Any]] = pickle.load(f)

        return index, metadata

    def clear(self) -> None:
        """清空索引和元数据。"""
        if self.metric == "cosine":
            self.index = faiss.IndexFlatIP(self.dimensions)
        else:
            self.index = faiss.IndexFlatL2(self.dimensions)
        self.metadata = []
