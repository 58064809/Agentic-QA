"""Retriever — TopK 召回并组装 RAG 上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rag.splitter import Chunk


@dataclass
class RetrievedDocument:
    """召回结果。"""
    text: str
    source: str
    heading: str
    score: float
    chunk_index: int


@dataclass
class RetrievalResult:
    """一次检索的完整结果。"""
    query: str
    documents: list[RetrievedDocument] = field(default_factory=list)
    total_chunks: int = 0
    used_knowledge_paths: list[str] = field(default_factory=list)

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
        "以下是从 QA 知识库中检索到的相关参考内容，请结合需求文档使用：\n\n"
        + "\n\n".join(sections)
    )
