"""RAG 配置。

通过环境变量或 config.yaml 控制 RAG 行为。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

# 环境变量 key
RAG_ENABLED_ENV = "RAG_ENABLED"
RAG_TOP_K_ENV = "RAG_TOP_K"
RAG_CHUNK_SIZE_ENV = "RAG_CHUNK_SIZE"
RAG_CHUNK_OVERLAP_ENV = "RAG_CHUNK_OVERLAP"
RAG_EMBEDDING_MODEL_ENV = "RAG_EMBEDDING_MODEL"
RAG_EMBEDDING_DIM_ENV = "RAG_EMBEDDING_DIM"
RAG_VECTOR_STORE_ENV = "RAG_VECTOR_STORE"
RAG_INDEX_DIR_ENV = "RAG_INDEX_DIR"
RAG_KNOWLEDGE_PATHS_ENV = "RAG_KNOWLEDGE_PATHS"

# 默认值
DEFAULT_ENABLED = False
DEFAULT_TOP_K = 5
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIM = 1536
DEFAULT_VECTOR_STORE = "faiss"
DEFAULT_INDEX_DIR = ".rag_index"
DEFAULT_KNOWLEDGE_PATHS = "knowledge/"


def _parse_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return default


def _parse_list(value: str | None, default: list[str]) -> list[str]:
    if value is None or not value.strip():
        return default
    return [p.strip() for p in value.split(",") if p.strip()]


@dataclass(frozen=True)
class RagConfig:
    """RAG 完整配置。"""

    enabled: bool = DEFAULT_ENABLED
    top_k: int = DEFAULT_TOP_K
    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dim: int = DEFAULT_EMBEDDING_DIM
    vector_store: str = DEFAULT_VECTOR_STORE
    index_dir: str = DEFAULT_INDEX_DIR
    knowledge_paths: list[str] = field(default_factory=lambda: list(DEFAULT_KNOWLEDGE_PATHS))
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> RagConfig:
        env = environ or os.environ
        warnings: list[str] = []

        enabled = _parse_bool(env.get(RAG_ENABLED_ENV))
        top_k = _parse_int(env.get(RAG_TOP_K_ENV), DEFAULT_TOP_K)
        chunk_size = _parse_int(env.get(RAG_CHUNK_SIZE_ENV), DEFAULT_CHUNK_SIZE)
        chunk_overlap = _parse_int(env.get(RAG_CHUNK_OVERLAP_ENV), DEFAULT_CHUNK_OVERLAP)
        embedding_model = env.get(RAG_EMBEDDING_MODEL_ENV) or DEFAULT_EMBEDDING_MODEL
        embedding_dim = _parse_int(env.get(RAG_EMBEDDING_DIM_ENV), DEFAULT_EMBEDDING_DIM)
        vector_store = env.get(RAG_VECTOR_STORE_ENV) or DEFAULT_VECTOR_STORE
        index_dir = env.get(RAG_INDEX_DIR_ENV) or DEFAULT_INDEX_DIR
        knowledge_paths = _parse_list(env.get(RAG_KNOWLEDGE_PATHS_ENV), [DEFAULT_KNOWLEDGE_PATHS])

        if top_k < 1:
            warnings.append(f"RAG_TOP_K={top_k} 无效，已使用默认值 {DEFAULT_TOP_K}")
            top_k = DEFAULT_TOP_K
        if chunk_size < 50:
            warnings.append(f"RAG_CHUNK_SIZE={chunk_size} 太小，已使用默认值 {DEFAULT_CHUNK_SIZE}")
            chunk_size = DEFAULT_CHUNK_SIZE

        return cls(
            enabled=enabled,
            top_k=top_k,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
            vector_store=vector_store,
            index_dir=index_dir,
            knowledge_paths=knowledge_paths,
            warnings=tuple(warnings),
        )

    @classmethod
    def from_dict(cls, data: dict | None) -> RagConfig:
        """从 YAML 配置字典合并环境变量。"""
        env = dict(os.environ)
        if data:
            for key, value in data.items():
                env_key = f"RAG_{key.upper()}"
                if env_key not in env and value is not None:
                    env[env_key] = str(value)
        return cls.from_env(env)

    @property
    def enabled_top_k(self) -> int:
        return self.top_k if self.enabled else 0
