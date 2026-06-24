"""RAG 模块单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag.config import RagConfig
from rag.embedding import (
    OPENAI_COMPATIBLE_BATCH_SIZE,
    LocalHashEmbeddingAdapter,
    OpenAIEmbeddingAdapter,
    compute_similarity,
)
from rag.loaders import find_markdown_files, load_markdown_files
from rag.manager import RagManager
from rag.retriever import (
    RetrievalResult,
    RetrievedDocument,
    assemble_rag_context,
)
from rag.splitter import Chunk, chunk_markdown_files, split_markdown_by_headings
from rag.vector_store import MemoryVectorStore


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
        assert c.embedding_provider == "auto"
        assert c.use_llm_api_key is True
        assert c.knowledge_paths == ["knowledge/"]

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

    def test_from_dict_list_paths(self) -> None:
        c = RagConfig.from_dict({"knowledge_paths": ["knowledge/a", "knowledge/b"]})
        assert c.knowledge_paths == ["knowledge/a", "knowledge/b"]

    def test_from_app_config_env_still_wins(self) -> None:
        c = RagConfig.from_app_config(
            {"enabled": True, "top_k": 7, "use_llm_api_key": False},
            {"RAG_TOP_K": "2"},
        )
        assert c.enabled is True
        assert c.top_k == 2
        assert c.use_llm_api_key is False

    def test_invalid_overlap_is_adjusted(self) -> None:
        c = RagConfig.from_env({"RAG_CHUNK_SIZE": "100", "RAG_CHUNK_OVERLAP": "100"})
        assert c.chunk_overlap == 20
        assert c.warnings

    def test_invalid_query_max_chars_is_adjusted(self) -> None:
        c = RagConfig.from_env({"RAG_QUERY_MAX_CHARS": "10"})
        assert c.query_max_chars == 8000
        assert c.warnings

    def test_enabled_top_k(self) -> None:
        c_disabled = RagConfig(enabled=False, top_k=5)
        assert c_disabled.enabled_top_k == 0
        c_enabled = RagConfig(enabled=True, top_k=5)
        assert c_enabled.enabled_top_k == 5


class TestLoaders:
    def test_find_markdown_files_nonexistent_dir(self) -> None:
        files = find_markdown_files(Path("nonexistent_path_xyz"))
        assert files == []

    def test_find_markdown_files_accepts_single_file(self, tmp_path: Path) -> None:
        md = tmp_path / "single.md"
        md.write_text("# 单文件\n", encoding="utf-8")
        assert find_markdown_files(md) == [md]

    def test_load_markdown_files_empty_paths(self) -> None:
        files = load_markdown_files([], Path())
        assert files == {}

    def test_load_markdown_files_truncates_large_file(self, tmp_path: Path) -> None:
        md = tmp_path / "long.md"
        md.write_text("a" * 100, encoding="utf-8")
        files = load_markdown_files([md], tmp_path, max_chars_per_file=10)
        assert files["long.md"] == "a" * 10

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
            self.SAMPLE_MD,
            "test.md",
            max_chars=500,
            min_chars=10,
        )
        assert len(chunks) >= 2
        assert all(isinstance(c, Chunk) for c in chunks)
        assert all(c.source == "test.md" for c in chunks)

    def test_split_with_heading_metadata(self) -> None:
        chunks = split_markdown_by_headings(
            self.SAMPLE_MD,
            "test.md",
            max_chars=500,
            min_chars=10,
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

    def test_overlap_for_long_plain_text(self) -> None:
        text = "0123456789" * 30
        chunks = split_markdown_by_headings(
            text,
            "plain.md",
            max_chars=100,
            min_chars=20,
            overlap=10,
        )
        assert len(chunks) >= 3
        assert chunks[0].text[-10:] == chunks[1].text[:10]


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
                chunk_id="knowledge/qa-methodology/scenario-testing.md#chunk-0",
                rank=1,
            )
        )
        assert result.has_results is True
        assert "测试登录流程" in result.context_text
        assert "测试场景" in result.context_text
        trace = result.to_trace()
        assert trace["pipeline"] == [
            "document",
            "chunk",
            "index",
            "retrieve",
            "rerank",
            "context_build",
            "generate",
        ]
        assert trace["retrieval_count"] == 1
        assert trace["documents"][0]["chunk_id"]
        assert trace["documents"][0]["rank"] == 1

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


class TestEmbeddingAndVectorStore:
    def test_local_hash_embedding_is_deterministic(self) -> None:
        embedder = LocalHashEmbeddingAdapter(dimensions=64)
        first = embedder.embed_text("边界值 登录")
        second = embedder.embed_text("边界值 登录")
        assert first == second
        assert compute_similarity(first, second) == pytest.approx(1.0)

    def test_openai_embedding_batches_large_inputs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        class FakeEmbeddingItem:
            def __init__(self, index: int) -> None:
                self.index = index
                self.embedding = [float(index)] * 4

        class FakeEmbeddings:
            def create(self, **kwargs):
                inputs = kwargs["input"]
                calls.append(inputs)

                class Response:
                    data = [FakeEmbeddingItem(index) for index in range(len(inputs))]

                return Response()

        class FakeClient:
            embeddings = FakeEmbeddings()

        monkeypatch.setattr("rag.embedding.OpenAI", lambda **_: FakeClient())
        adapter = OpenAIEmbeddingAdapter(
            api_key="test-key",
            model="text-embedding-v4",
            dimensions=4,
        )

        vectors = adapter.embed_batch(
            [f"text-{index}" for index in range(OPENAI_COMPATIBLE_BATCH_SIZE + 3)]
        )

        assert [len(call) for call in calls] == [10, 3]
        assert len(vectors) == 13

    def test_memory_vector_store_search_and_persist(self, tmp_path: Path) -> None:
        embedder = LocalHashEmbeddingAdapter(dimensions=64)
        store = MemoryVectorStore(dimensions=64)
        vectors = embedder.embed_batch(["边界值分析", "状态迁移测试"])
        store.add(vectors, [{"source": "a.md"}, {"source": "b.md"}])

        results = store.search(embedder.embed_text("边界值"), top_k=1)
        assert results[0][0]["source"] == "a.md"

        store.save(tmp_path)
        loaded = MemoryVectorStore(dimensions=64, index_path=tmp_path)
        assert loaded.size == 2


class TestRagManager:
    def test_local_memory_rag_retrieves_context(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "knowledge"
        knowledge.mkdir()
        (knowledge / "boundary.md").write_text(
            "# 边界值分析\n\n边界值分析适合校验输入范围的最小值、最大值和越界值。",
            encoding="utf-8",
        )
        (knowledge / "state.md").write_text(
            "# 状态迁移测试\n\n状态迁移测试适合校验状态流转和非法状态切换。",
            encoding="utf-8",
        )

        config = RagConfig(
            enabled=True,
            embedding_provider="local",
            embedding_dim=64,
            vector_store="memory",
            index_dir=".rag_test_index",
            knowledge_paths=["knowledge"],
            chunk_size=120,
            chunk_overlap=10,
        )
        manager = RagManager(tmp_path, config)

        build = manager.build_index(force_rebuild=True)
        assert build["index_size"] == 2

        result = manager.retrieve("输入框范围边界值怎么测", top_k=1)
        assert result.has_results
        assert "边界值分析" in result.documents[0].text
        assert "RAG 知识库上下文" in manager.build_rag_context("输入框范围边界值怎么测")

    def test_retrieve_truncates_long_query(self, tmp_path: Path) -> None:
        knowledge = tmp_path / "knowledge"
        knowledge.mkdir()
        (knowledge / "boundary.md").write_text(
            "# 边界值分析\n\n"
            "边界值分析适合校验输入范围、最小值、最大值、越界值和关键业务阈值。"
            "测试设计时需要覆盖 N-1、N、N+1，并明确每个边界的预期结果。",
            encoding="utf-8",
        )
        config = RagConfig(
            enabled=True,
            embedding_provider="local",
            embedding_dim=64,
            vector_store="memory",
            index_dir=".rag_test_index",
            knowledge_paths=["knowledge"],
            query_max_chars=20,
        )
        manager = RagManager(tmp_path, config)
        manager.build_index(force_rebuild=True)

        result = manager.retrieve("边界值分析" + "x" * 1000, top_k=1)

        assert result.has_results
