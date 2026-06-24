"""RAG Manager — 编排嵌入、索引、检索全流程。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from rag.config import RagConfig
from rag.embedding import EmbeddingAdapter, LocalHashEmbeddingAdapter, OpenAIEmbeddingAdapter
from rag.loaders import load_markdown_files
from rag.retriever import RetrievalResult, RetrievedDocument, assemble_rag_context
from rag.splitter import Chunk, chunk_markdown_files
from rag.vector_store import FaissVectorStore, MemoryVectorStore
from runtime.config import load_app_config
from runtime.llm.config import API_KEY_ENV as LLM_API_KEY_ENV
from runtime.llm.config import OpenAICompatibleConfig


def _chunk_id(source: str, chunk_index: int) -> str:
    return f"{source}#chunk-{chunk_index}"


def _content_hash(files: dict[str, str]) -> str:
    """对加载的文件内容计算哈希，用于判断索引是否需要重建。"""
    sorted_items = sorted(files.items())
    raw = json.dumps(sorted_items, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


MANIFEST_FILE = "manifest.json"
CONTENT_HASH_FILE = "content_hash.txt"


class RagManager:
    """RAG 管理器 — 单例风格，管理知识库的加载、索引和检索。

    使用方式：
        manager = RagManager(repo_root, config)
        manager.build_index()          # 首次构建
        result = manager.retrieve(query)  # 检索
    """

    def __init__(
        self,
        repo_root: Path,
        config: RagConfig | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.config = config or RagConfig.from_app_config(load_app_config(self.repo_root).rag)

        self._embedder: EmbeddingAdapter | None = None
        self._vector_store: FaissVectorStore | MemoryVectorStore | None = None
        self._chunks: list[Chunk] = []
        self._index_built = False
        self._index_hash = ""
        self._index_dir = repo_root / self.config.index_dir
        self._last_build_result: dict[str, Any] = {}

    # ---- 初始化 ----

    def _ensure_embedder(self) -> EmbeddingAdapter:
        if self._embedder is not None:
            return self._embedder

        llm_config = OpenAICompatibleConfig.from_env()
        rag_api_key = os.environ.get(self.config.api_key_env) or None
        reusable_llm_key = llm_config.api_key if self.config.use_llm_api_key else None
        api_key = rag_api_key or reusable_llm_key
        base_url = self.config.base_url or llm_config.base_url
        provider = self.config.embedding_provider
        if provider == "auto":
            provider = "openai" if api_key else "local"

        if provider == "local":
            self._embedder = LocalHashEmbeddingAdapter(dimensions=self.config.embedding_dim)
            return self._embedder

        if not api_key:
            raise RuntimeError(
                "RAG 需要 Embedding API Key。请设置 "
                f"{self.config.api_key_env}，或设置 RAG_USE_LLM_API_KEY=true 后复用 "
                f"{LLM_API_KEY_ENV}。"
            )

        self._embedder = OpenAIEmbeddingAdapter(
            api_key=api_key,
            model=self.config.embedding_model,
            base_url=base_url,
            dimensions=self.config.embedding_dim,
        )
        return self._embedder

    def _ensure_vector_store(
        self,
        *,
        load_persisted: bool = True,
    ) -> FaissVectorStore | MemoryVectorStore:
        if self._vector_store is not None:
            return self._vector_store

        index_path = self._index_dir if load_persisted and self._index_dir.exists() else None
        if self.config.vector_store == "memory":
            self._vector_store = MemoryVectorStore(
                dimensions=self.config.embedding_dim,
                index_path=str(index_path) if index_path else None,
            )
        else:
            try:
                self._vector_store = FaissVectorStore(
                    dimensions=self.config.embedding_dim,
                    index_path=str(index_path) if index_path else None,
                )
            except RuntimeError:
                self._vector_store = MemoryVectorStore(
                    dimensions=self.config.embedding_dim,
                    index_path=str(index_path) if index_path else None,
                )
        return self._vector_store

    # ---- 索引构建 ----

    def _index_manifest(self, *, content_hash: str) -> dict[str, Any]:
        return {
            "schema_version": "agentic-qa.rag-index.v1",
            "content_hash": content_hash,
            "embedding_provider": self.config.embedding_provider,
            "embedding_model": self.config.embedding_model,
            "embedding_dim": self.config.embedding_dim,
            "vector_store": self.config.vector_store,
            "chunk_size": self.config.chunk_size,
            "chunk_overlap": self.config.chunk_overlap,
            "knowledge_paths": list(self.config.knowledge_paths),
            "max_file_chars": self.config.max_file_chars,
        }

    def _read_manifest(self) -> dict[str, Any]:
        path = self._index_dir / MANIFEST_FILE
        if not path.is_file():
            return {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _manifest_matches(self, expected: dict[str, Any]) -> bool:
        current = self._read_manifest()
        return all(current.get(key) == value for key, value in expected.items())

    def build_index(self, *, force_rebuild: bool = False) -> dict[str, Any]:
        """加载知识库文档 → 切分 → 嵌入 → 构建 FAISS 索引。

        Returns:
            {"chunks": int, "index_size": int, "knowledge_paths": list[str], "rebuilt": bool}
        """
        # 加载文档
        files = load_markdown_files(
            self.config.knowledge_paths,
            self.repo_root,
            max_chars_per_file=self.config.max_file_chars,
        )
        if not files:
            return {
                "chunks": 0,
                "index_size": 0,
                "knowledge_paths": self.config.knowledge_paths,
                "rebuilt": False,
                "warning": "未找到知识库文档，RAG 索引为空。",
            }

        content_hash = _content_hash(files)
        expected_manifest = self._index_manifest(content_hash=content_hash)

        # 如果索引已存在且内容未变，跳过重建
        if (
            not force_rebuild
            and self._index_built
            and self._index_hash == content_hash
            and self._manifest_matches(expected_manifest)
        ):
            self._last_build_result = {
                "chunks": len(self._chunks),
                "index_size": self._ensure_vector_store().size,
                "knowledge_paths": self.config.knowledge_paths,
                "rebuilt": False,
                "manifest": expected_manifest,
            }
            return self._last_build_result

        # 如果有持久化索引且哈希匹配，直接加载
        if not force_rebuild:
            hash_file = self._index_dir / CONTENT_HASH_FILE
            has_matching_hash = (
                hash_file.is_file()
                and hash_file.read_text(encoding="utf-8").strip() == content_hash
                and self._manifest_matches(expected_manifest)
            )
            if has_matching_hash:
                vs = self._ensure_vector_store()
                if vs.size > 0:
                    self._chunks = []  # 从持久化加载的元数据恢复 chunks 信息
                    self._index_built = True
                    self._index_hash = content_hash
                    self._last_build_result = {
                        "chunks": vs.size,
                        "index_size": vs.size,
                        "knowledge_paths": self.config.knowledge_paths,
                        "rebuilt": False,
                        "loaded_from_disk": True,
                        "manifest": expected_manifest,
                    }
                    return self._last_build_result

        # 切分
        chunks = chunk_markdown_files(
            files,
            max_chars=self.config.chunk_size,
            min_chars=min(50, max(10, self.config.chunk_size // 5)),
            overlap=self.config.chunk_overlap,
        )
        if not chunks:
            return {
                "chunks": 0,
                "index_size": 0,
                "knowledge_paths": self.config.knowledge_paths,
                "rebuilt": False,
                "warning": "文档切分后 Chunk 为空。",
            }

        # 生成 Embedding
        embedder = self._ensure_embedder()
        texts = [c.text for c in chunks]
        vectors = embedder.embed_batch(texts)

        # 构建 FAISS 索引
        metadata: list[dict[str, Any]] = [
            {
                "source": c.source,
                "chunk_id": _chunk_id(c.source, c.chunk_index),
                "heading": c.heading,
                "chunk_index": c.chunk_index,
                "text": c.text,
            }
            for c in chunks
        ]
        vector_store = self._ensure_vector_store(load_persisted=False)
        vector_store.clear()
        vector_store.add(vectors, metadata)

        # 持久化
        self._index_dir.mkdir(parents=True, exist_ok=True)
        vector_store.save(self._index_dir)
        hash_file = self._index_dir / CONTENT_HASH_FILE
        hash_file.write_text(content_hash, encoding="utf-8")
        (self._index_dir / MANIFEST_FILE).write_text(
            json.dumps(expected_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        self._chunks = chunks
        self._index_built = True
        self._index_hash = content_hash

        self._last_build_result = {
            "chunks": len(chunks),
            "index_size": vector_store.size,
            "knowledge_paths": self.config.knowledge_paths,
            "rebuilt": True,
            "manifest": expected_manifest,
        }
        return self._last_build_result

    # ---- 检索 ----

    def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
    ) -> RetrievalResult:
        """检索与查询最相关的知识库文档。

        Args:
            query: 检索查询文本
            top_k: 返回条数（默认使用配置值）

        Returns:
            RetrievalResult 包含召回文档和拼装上下文
        """
        result = RetrievalResult(
            query=query,
            used_knowledge_paths=list(self.config.knowledge_paths),
            index_metadata=self._read_manifest(),
        )

        if not self.config.enabled:
            return result

        k = top_k or self.config.top_k
        if k <= 0:
            return result

        if not self._index_built:
            # 尝试从磁盘加载或自动构建
            build_result = self.build_index()
            result.index_metadata = self._read_manifest() or build_result.get("manifest", {})
            if build_result.get("index_size", 0) == 0:
                return result

        vector_store = self._ensure_vector_store()
        if vector_store.size == 0:
            return result

        # 查询嵌入
        try:
            embedder = self._ensure_embedder()
            query_text = query[: self.config.query_max_chars]
            result.query_text = query_text
            query_vector = embedder.embed_text(query_text)
        except Exception as exc:
            result.error = str(exc)
            return result

        # 搜索
        raw_results = vector_store.search(query_vector, top_k=k)
        result.total_chunks = vector_store.size

        for rank, (metadata, score) in enumerate(raw_results, start=1):
            doc = RetrievedDocument(
                text=metadata.get("text", ""),
                source=metadata.get("source", ""),
                heading=metadata.get("heading", ""),
                score=score,
                rank=rank,
                chunk_id=metadata.get("chunk_id", "")
                or _chunk_id(metadata.get("source", ""), metadata.get("chunk_index", 0)),
                chunk_index=metadata.get("chunk_index", 0),
            )
            result.documents.append(doc)

        return result

    # ---- 快捷方法 ----

    def build_rag_context(
        self,
        query: str,
        *,
        top_k: int | None = None,
        max_chars: int = 4000,
    ) -> str:
        """一键检索并组装 RAG 上下文字符串。

        如果 RAG 未启用或检索失败，返回空字符串。
        """
        retrieval = self.retrieve(query, top_k=top_k)
        if not retrieval.has_results:
            return ""
        return assemble_rag_context(retrieval, max_chars=max_chars)

    @property
    def is_ready(self) -> bool:
        """RAG 是否已就绪（启用且有索引）。"""
        if not self.config.enabled:
            return False
        if self._index_built:
            return True
        # 检查持久化索引是否存在
        index_file = self._index_dir / "index.faiss"
        memory_index_file = self._index_dir / "memory_index.json"
        return index_file.is_file() or memory_index_file.is_file()

    @property
    def stats(self) -> dict[str, Any]:
        """当前 RAG 状态统计。"""
        index_ready = self.is_ready
        vs = self._ensure_vector_store() if index_ready else None
        return {
            "enabled": self.config.enabled,
            "index_built": self._index_built,
            "index_ready": index_ready,
            "index_size": vs.size if vs else 0,
            "chunks_count": len(self._chunks),
            "top_k": self.config.top_k,
            "embedding_model": self.config.embedding_model,
            "embedding_provider": self.config.embedding_provider,
            "use_llm_api_key": self.config.use_llm_api_key,
            "api_key_env": self.config.api_key_env,
            "vector_store": self.config.vector_store,
            "knowledge_paths": self.config.knowledge_paths,
            "index_manifest": self._read_manifest(),
        }
