"""Retriever — TopK 召回并组装 RAG 上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RetrievedDocument:
    """召回结果。"""

    text: str
    source: str
    heading: str
    score: float
    chunk_index: int

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "heading": self.heading,
            "score": self.score,
            "chunk_index": self.chunk_index,
            "text_preview": self.text[:300],
        }


@dataclass
class RetrievalResult:
    """一次检索的完整结果。"""

    query: str
    documents: list[RetrievedDocument] = field(default_factory=list)
    total_chunks: int = 0
    used_knowledge_paths: list[str] = field(default_factory=list)
    error: str = ""
    query_text: str = ""
    index_metadata: dict[str, object] = field(default_factory=dict)

    @property
    def context_text(self) -> str:
        """将召回文档拼接到上下文字符串。"""
        if not self.documents:
            return ""
        sections: list[str] = []
        for i, doc in enumerate(self.documents, 1):
            header = f"### 知识库引用 {i}（来源: {doc.source}，相似度: {doc.score:.3f}）"
            if doc.heading:
                header += f"\n> 章节: {doc.heading}"
            sections.append(f"{header}\n\n{doc.text}")
        return "\n\n".join(sections)

    @property
    def has_results(self) -> bool:
        return len(self.documents) > 0

    @property
    def has_error(self) -> bool:
        return bool(self.error)

    def to_trace(self) -> dict[str, object]:
        return {
            "query": self.query,
            "query_text": self.query_text,
            "total_chunks": self.total_chunks,
            "used_knowledge_paths": self.used_knowledge_paths,
            "error": self.error,
            "index_metadata": self.index_metadata,
            "documents": [doc.to_dict() for doc in self.documents],
        }


def assemble_rag_context(
    retrieval: RetrievalResult,
    *,
    max_chars: int = 4000,
) -> str:
    """将检索结果组装为注入 Prompt 的 RAG 上下文。

    若超过 max_chars，按分数从高到低截断。
    """
    if not retrieval.has_results:
        return ""

    sections: list[str] = []
    accumulated = 0
    # 按分数降序排列
    sorted_docs = sorted(retrieval.documents, key=lambda d: d.score, reverse=True)

    for doc in sorted_docs:
        header = f"### 知识库引用（来源: {doc.source}）"
        if doc.heading:
            header += f"\n> 章节: {doc.heading}"
        block = f"{header}\n\n{doc.text}"
        if accumulated + len(block) > max_chars:
            break
        sections.append(block)
        accumulated += len(block)

    if not sections:
        return ""

    return (
        "## RAG 知识库上下文\n\n"
        "以下是从 QA 知识库中检索到的相关参考内容，请结合需求文档使用：\n\n" + "\n\n".join(sections)
    )
