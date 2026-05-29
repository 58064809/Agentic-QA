"""RAG 模块单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag.config import RagConfig
from rag.loaders import find_markdown_files, load_markdown_files
from rag.retriever import (
    RetrievedDocument,
    RetrievalResult,
    assemble_rag_context,
)
from rag.splitter import Chunk, chunk_markdown_files, split_markdown_by_headings


class TestRagConfig:
    def test_default_values(self) -> None:
        c = RagConfig()
        assert c.enabled is False
        assert c.top_k == 5
        assert c.chunk_size == 500
        assert c.chunk_overlap == 50
        assert c.embedding_model == "text-embedding-3-small"
        assert c.embedding_dim == 1536
        assert c.vector_store == "faiss"

    def test_from_env_defaults(self) -> None:
        c = RagConfig.from_env({"RAG_ENABLED": "true", "RAG_TOP_K": "3"})
        assert c.enabled is True
        assert c.top_k == 3

    def test_from_env_bool(self) -> None:
        for val in ("1", "true", "True", "yes", "on"):
            c = RagConfig.from_env({"RAG_ENABLED": val})
            assert c.enabled is True
        for val in ("0", "false", "no", "off", ""):
            c = RagConfig.from_env({"RAG_ENABLED": val})
            assert c.enabled is False

    def test_from_env_invalid_int_falls_back(self) -> None:
        c = RagConfig.from_env({"RAG_TOP_K": "not_a_number"})
        assert c.top_k == 5

    def test_from_dict(self) -> None:
        c = RagConfig.from_dict({"enabled": True, "top_k": 7, "chunk_size": 300})
        assert c.enabled is True
        assert c.top_k == 7
        assert c.chunk_size == 300

    def test_enabled_top_k(self) -> None:
        c_disabled = RagConfig(enabled=False, top_k=5)
        assert c_disabled.enabled_top_k == 0
        c_enabled = RagConfig(enabled=True, top_k=5)
        assert c_enabled.enabled_top_k == 5


class TestLoaders:
    def test_find_markdown_files_nonexistent_dir(self) -> None:
        files = find_markdown_files(Path("nonexistent_path_xyz"))
        assert files == []

    def test_load_markdown_files_empty_paths(self) -> None:
        files = load_markdown_files([], Path())
        assert files == {}

    def test_load_markdown_knowledge_dir(self) -> None:
        repo_root = Path().resolve()
        files = load_markdown_files(
            ["knowledge/qa-methodology", "knowledge/project-rules"],
            repo_root,
        )
        assert len(files) >= 2
        # 应包含 qa-methodology 中的文件
        assert any("equivalence-partitioning" in k for k in files)
        assert any("boundary-value-analysis" in k for k in files)


class TestSplitter:
    SAMPLE_MD = (
        "# 测试文档\n\n"
        "这是文档简介。\n\n"
        "## 第一节\n\n"
        "这是第一节的内容，包含一些测试文本。\n\n"
        "### 第一节.1\n\n"
        "这是子章节。\n\n"
        "## 第二节\n\n"
        "这是第二节的内容。\n\n"
    )

    def test_split_by_headings(self) -> None:
        chunks = split_markdown_by_headings(
            self.SAMPLE_MD, "test.md", max_chars=500, min_chars=10,
        )
        assert len(chunks) >= 2
        assert all(isinstance(c, Chunk) for c in chunks)
        assert all(c.source == "test.md" for c in chunks)

    def test_split_with_heading_metadata(self) -> None:
        chunks = split_markdown_by_headings(
            self.SAMPLE_MD, "test.md", max_chars=500, min_chars=10,
        )
        assert chunks[0].heading == "测试文档"
        first_headings = {c.heading for c in chunks}
        assert "测试文档" in first_headings

    def test_empty_text(self) -> None:
        chunks = split_markdown_by_headings("", "empty.md")
        assert chunks == []

    def test_no_headings(self) -> None:
        text = "段落一。\n\n段落二。\n\n段落三。" * 50
        chunks = split_markdown_by_headings(text, "plain.md", max_chars=200, min_chars=20)
        assert len(chunks) >= 1

    def test_chunk_markdown_files(self) -> None:
        files = {
            "doc1.md": "# Doc 1\n\n内容一。\n\n## 子节\n\n子节内容。" * 5,
            "doc2.md": "# Doc 2\n\n内容二。" * 3,
        }
        chunks = chunk_markdown_files(files, max_chars=500, min_chars=20)
        assert len(chunks) >= 2
        sources = {c.source for c in chunks}
        assert "doc1.md" in sources
        assert "doc2.md" in sources


class TestRetriever:
    def test_basic_retrieval_result(self) -> None:
        result = RetrievalResult(query="test query")
        assert result.has_results is False
        assert result.context_text == ""
        assert assemble_rag_context(result) == ""

    def test_with_documents(self) -> None:
        result = RetrievalResult(query="login test")
        result.documents.append(
            RetrievedDocument(
                text="测试登录流程需要用户名和密码。",
                source="knowledge/qa-methodology/scenario-testing.md",
                heading="测试场景",
                score=0.92,
                chunk_index=0,
            )
        )
        assert result.has_results is True
        assert "测试登录流程" in result.context_text
        assert "测试场景" in result.context_text

    def test_assemble_rag_context_format(self) -> None:
        result = RetrievalResult(query="边界值分析")
        result.documents.append(
            RetrievedDocument(
                text="边界值分析是一种黑盒测试技术。",
                source="knowledge/qa-methodology/boundary-value-analysis.md",
                heading="边界值分析",
                score=0.95,
                chunk_index=0,
            )
        )
        ctx = assemble_rag_context(result)
        assert "## RAG 知识库上下文" in ctx
        assert "边界值分析" in ctx
        assert "knowledge/qa-methodology" in ctx

    def test_max_chars_truncation(self) -> None:
        result = RetrievalResult(query="test")
        # 添加大量内容
        for i in range(10):
            result.documents.append(
                RetrievedDocument(
                    text=f"测试内容第{i}段。" * 100,
                    source=f"doc{i}.md",
                    heading=f"章节{i}",
                    score=1.0 - i * 0.1,
                    chunk_index=i,
                )
            )
        ctx = assemble_rag_context(result, max_chars=500)
        # 截断后总字符数应不超过 max_chars + 一些头部开销
        assert len(ctx) < 2000  # 应该远小于完整内容的长度

    def test_score_sorting(self) -> None:
        result = RetrievalResult(query="test")
        result.documents.append(
            RetrievedDocument(text="low", source="a.md", heading="", score=0.3, chunk_index=0)
        )
        result.documents.append(
            RetrievedDocument(text="high", source="b.md", heading="", score=0.9, chunk_index=1)
        )
        # assemble_rag_context 内部会按分数排序
        ctx = assemble_rag_context(result, max_chars=500)
        # 高分的应排在前面
        high_pos = ctx.index("high")
        low_pos = ctx.index("low")
        assert high_pos < low_pos
