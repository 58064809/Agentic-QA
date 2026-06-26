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
RAG_EMBEDDING_PROVIDER_ENV = "RAG_EMBEDDING_PROVIDER"
RAG_USE_LLM_API_KEY_ENV = "RAG_USE_LLM_API_KEY"
RAG_API_KEY_ENV = "RAG_API_KEY"
RAG_BASE_URL_ENV = "RAG_BASE_URL"
RAG_EMBEDDING_DIM_ENV = "RAG_EMBEDDING_DIM"
RAG_VECTOR_STORE_ENV = "RAG_VECTOR_STORE"
RAG_INDEX_DIR_ENV = "RAG_INDEX_DIR"
RAG_KNOWLEDGE_PATHS_ENV = "RAG_KNOWLEDGE_PATHS"
RAG_MAX_FILE_CHARS_ENV = "RAG_MAX_FILE_CHARS"
RAG_QUERY_MAX_CHARS_ENV = "RAG_QUERY_MAX_CHARS"

# 默认值
DEFAULT_ENABLED = False
DEFAULT_TOP_K = 5
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
DEFAULT_EMBEDDING_PROVIDER = "auto"
DEFAULT_USE_LLM_API_KEY = True
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIM = 1536
DEFAULT_VECTOR_STORE = "faiss"
DEFAULT_INDEX_DIR = ".rag_index"
DEFAULT_KNOWLEDGE_PATHS = ("knowledge/",)
DEFAULT_MAX_FILE_CHARS = 200_000
DEFAULT_QUERY_MAX_CHARS = 8_000
SUPPORTED_EMBEDDING_PROVIDERS = {"auto", "openai", "local"}
SUPPORTED_VECTOR_STORES = {"faiss", "memory"}


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
    embedding_provider: str = DEFAULT_EMBEDDING_PROVIDER
    use_llm_api_key: bool = DEFAULT_USE_LLM_API_KEY
    api_key_env: str = RAG_API_KEY_ENV
    base_url: str | None = None
    knowledge_paths: list[str] = field(default_factory=lambda: list(DEFAULT_KNOWLEDGE_PATHS))
    max_file_chars: int = DEFAULT_MAX_FILE_CHARS
    query_max_chars: int = DEFAULT_QUERY_MAX_CHARS
    warnings: tuple[str, ...] = ()

    def __getitem__(self, key: str):
        return getattr(self, key)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> RagConfig:
        env = environ or os.environ
        warnings: list[str] = []

        enabled = _parse_bool(env.get(RAG_ENABLED_ENV))
        top_k = _parse_int(env.get(RAG_TOP_K_ENV), DEFAULT_TOP_K)
        chunk_size = _parse_int(env.get(RAG_CHUNK_SIZE_ENV), DEFAULT_CHUNK_SIZE)
        chunk_overlap = _parse_int(env.get(RAG_CHUNK_OVERLAP_ENV), DEFAULT_CHUNK_OVERLAP)
        embedding_provider = (
            (env.get(RAG_EMBEDDING_PROVIDER_ENV) or DEFAULT_EMBEDDING_PROVIDER).strip().lower()
        )
        use_llm_api_key = _parse_bool(env.get(RAG_USE_LLM_API_KEY_ENV), DEFAULT_USE_LLM_API_KEY)
        api_key_env = env.get("RAG_API_KEY_ENV") or RAG_API_KEY_ENV
        base_url = env.get(RAG_BASE_URL_ENV) or None
        embedding_model = env.get(RAG_EMBEDDING_MODEL_ENV) or DEFAULT_EMBEDDING_MODEL
        embedding_dim = _parse_int(env.get(RAG_EMBEDDING_DIM_ENV), DEFAULT_EMBEDDING_DIM)
        vector_store = (env.get(RAG_VECTOR_STORE_ENV) or DEFAULT_VECTOR_STORE).strip().lower()
        index_dir = env.get(RAG_INDEX_DIR_ENV) or DEFAULT_INDEX_DIR
        knowledge_paths = _parse_list(
            env.get(RAG_KNOWLEDGE_PATHS_ENV),
            list(DEFAULT_KNOWLEDGE_PATHS),
        )
        max_file_chars = _parse_int(env.get(RAG_MAX_FILE_CHARS_ENV), DEFAULT_MAX_FILE_CHARS)
        query_max_chars = _parse_int(env.get(RAG_QUERY_MAX_CHARS_ENV), DEFAULT_QUERY_MAX_CHARS)

        if top_k < 1:
            warnings.append(f"RAG_TOP_K={top_k} 无效，已使用默认值 {DEFAULT_TOP_K}")
            top_k = DEFAULT_TOP_K
        if chunk_size < 50:
            warnings.append(f"RAG_CHUNK_SIZE={chunk_size} 太小，已使用默认值 {DEFAULT_CHUNK_SIZE}")
            chunk_size = DEFAULT_CHUNK_SIZE
        if chunk_overlap < 0:
            warnings.append("RAG_CHUNK_OVERLAP 不能为负数，已使用默认值 0")
            chunk_overlap = 0
        if chunk_overlap >= chunk_size:
            adjusted = max(0, chunk_size // 5)
            warnings.append(
                f"RAG_CHUNK_OVERLAP={chunk_overlap} 必须小于 RAG_CHUNK_SIZE，已调整为 {adjusted}"
            )
            chunk_overlap = adjusted
        if embedding_provider not in SUPPORTED_EMBEDDING_PROVIDERS:
            warnings.append(
                f"RAG_EMBEDDING_PROVIDER={embedding_provider} 不支持，"
                f"已使用 {DEFAULT_EMBEDDING_PROVIDER}"
            )
            embedding_provider = DEFAULT_EMBEDDING_PROVIDER
        if embedding_dim < 8:
            warnings.append(
                f"RAG_EMBEDDING_DIM={embedding_dim} 太小，已使用默认值 {DEFAULT_EMBEDDING_DIM}"
            )
            embedding_dim = DEFAULT_EMBEDDING_DIM
        if vector_store not in SUPPORTED_VECTOR_STORES:
            warnings.append(
                f"RAG_VECTOR_STORE={vector_store} 不支持，已使用 {DEFAULT_VECTOR_STORE}"
            )
            vector_store = DEFAULT_VECTOR_STORE
        if max_file_chars < 1000:
            warnings.append(
                f"RAG_MAX_FILE_CHARS={max_file_chars} 太小，已使用默认值 {DEFAULT_MAX_FILE_CHARS}"
            )
            max_file_chars = DEFAULT_MAX_FILE_CHARS
        if query_max_chars < 1000:
            warnings.append(
                f"RAG_QUERY_MAX_CHARS={query_max_chars} 太小，"
                f"已使用默认值 {DEFAULT_QUERY_MAX_CHARS}"
            )
            query_max_chars = DEFAULT_QUERY_MAX_CHARS

        return cls(
            enabled=enabled,
            top_k=top_k,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embedding_provider=embedding_provider,
            use_llm_api_key=use_llm_api_key,
            api_key_env=api_key_env,
            base_url=base_url,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
            vector_store=vector_store,
            index_dir=index_dir,
            knowledge_paths=knowledge_paths,
            max_file_chars=max_file_chars,
            query_max_chars=query_max_chars,
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
                    if isinstance(value, list | tuple):
                        env[env_key] = ",".join(str(item) for item in value)
                    else:
                        env[env_key] = str(value)
        return cls.from_env(env)

    @classmethod
    def from_app_config(
        cls,
        data: dict | None,
        environ: Mapping[str, str] | None = None,
    ) -> RagConfig:
        """从统一配置中的 rag 段落合并环境变量。

        环境变量优先级高于 YAML 配置。
        """
        env = dict(environ or os.environ)
        if data:
            for key, value in data.items():
                env_key = f"RAG_{key.upper()}"
                if env_key not in env and value is not None:
                    if isinstance(value, list | tuple):
                        env[env_key] = ",".join(str(item) for item in value)
                    else:
                        env[env_key] = str(value)
        return cls.from_env(env)

    @property
    def enabled_top_k(self) -> int:
        return self.top_k if self.enabled else 0
