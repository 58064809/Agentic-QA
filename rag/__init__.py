"""RAG extension points for Agentic-QA.

Phase 4 implementation provides:
- Markdown document loading from knowledge/ directory
- Section-based Markdown chunking
- OpenAI-compatible embedding adapter
- FAISS vector store
- TopK retrieval with RAG context assembly
- Full lifecycle management via RagManager
"""

from __future__ import annotations

from rag.config import RagConfig
from rag.manager import RagManager
from rag.retriever import RetrievalResult, RetrievedDocument, assemble_rag_context

__all__ = [
    "RagConfig",
    "RagManager",
    "RetrievalResult",
    "RetrievedDocument",
    "assemble_rag_context",
]
