from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from rag.config import RagConfig  # noqa: E402
from rag.manager import RagManager  # noqa: E402
from runtime.cli.rag_cmds import run_rag_command  # noqa: E402
from runtime.graph.nodes.mvp_generation import (  # noqa: E402
    _build_rag_context,
    _build_rag_query,
)
from runtime.graph.state import QAWorkflowState  # noqa: E402


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_rag_config(root: Path) -> None:
    write_text(
        root / "configs" / "config.yaml",
        """
rag:
  enabled: true
  top_k: 2
  embedding_provider: local
  embedding_dim: 32
  vector_store: memory
  index_dir: .rag_test_index
  chunk_size: 120
  chunk_overlap: 10
  query_max_chars: 2000
  knowledge_paths:
    - knowledge
""".lstrip(),
    )


def test_index_manifest_prevents_reusing_stale_dimensions(tmp_path: Path) -> None:
    write_text(
        tmp_path / "knowledge" / "boundary.md",
        "# Boundary\n\nBoundary value analysis covers min, max and out-of-range inputs.",
    )

    first_config = RagConfig(
        enabled=True,
        embedding_provider="local",
        embedding_dim=64,
        vector_store="memory",
        index_dir=".rag_test_index",
        knowledge_paths=["knowledge"],
        chunk_size=120,
        chunk_overlap=10,
    )
    first = RagManager(tmp_path, first_config).build_index(force_rebuild=True)
    assert first["rebuilt"] is True
    assert first["manifest"]["embedding_dim"] == 64

    reused = RagManager(tmp_path, first_config).build_index()
    assert reused["rebuilt"] is False
    assert reused.get("loaded_from_disk") is True

    changed_config = RagConfig(
        enabled=True,
        embedding_provider="local",
        embedding_dim=32,
        vector_store="memory",
        index_dir=".rag_test_index",
        knowledge_paths=["knowledge"],
        chunk_size=120,
        chunk_overlap=10,
    )
    rebuilt = RagManager(tmp_path, changed_config).build_index()

    assert rebuilt["rebuilt"] is True
    assert rebuilt["manifest"]["embedding_dim"] == 32
    manifest = json.loads((tmp_path / ".rag_test_index" / "manifest.json").read_text("utf-8"))
    assert manifest["embedding_dim"] == 32


def test_build_rag_query_selects_headings_rules_and_risks() -> None:
    state = QAWorkflowState(
        user_input="analyze campaign requirement",
        prd_path="prd/demo",
    )
    state.loaded_files["prd/demo/input/requirement.md"] = "\n".join(
        [
            "# May Campaign",
            "This introductory line should not be selected.",
            "活动规则：用户每天最多领取 1 次奖励。",
            "字段：invite_count 表示邀请人数。",
            "风险：重复领取奖励需要拦截。",
            "This trailing line should not be selected.",
        ]
    )

    query = _build_rag_query(state, max_chars=500)

    assert "analyze campaign requirement" in query
    assert "# May Campaign" in query
    assert "活动规则" in query
    assert "invite_count" in query
    assert "重复领取" in query
    assert "introductory line" not in query


def test_build_rag_context_records_retrieval_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_rag_config(tmp_path)
    write_text(
        tmp_path / "knowledge" / "boundary.md",
        "# Boundary\n\nBoundary value analysis covers min, max and out-of-range inputs.",
    )
    monkeypatch.chdir(tmp_path)

    state = QAWorkflowState(
        user_input="analyze boundary rules",
        prd_path="prd/demo",
        task_type="requirement_analysis",
    )
    state.loaded_files["prd/demo/input/requirement.md"] = (
        "# Requirement\n\n规则：input amount must cover min and max boundary values."
    )

    context = _build_rag_context(state)

    assert "RAG" in context
    assert len(state.rag_retrievals) == 1
    trace = state.rag_retrievals[0]
    assert trace["node"] == "requirement_analysis"
    assert trace["documents"]
    assert trace["pipeline"] == [
        "document",
        "chunk",
        "index",
        "retrieve",
        "rerank",
        "context_build",
        "generate",
    ]
    assert trace["retrieval_count"] == len(trace["documents"])
    assert trace["documents"][0]["chunk_id"]
    assert trace["documents"][0]["rank"] == 1
    assert trace["index_metadata"]["embedding_dim"] == 32


def test_rag_cli_status_build_search(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_rag_config(tmp_path)
    write_text(
        tmp_path / "knowledge" / "state.md",
        "# State\n\nState transition testing covers valid and invalid status changes.",
    )

    assert run_rag_command(["status"], tmp_path) == 0
    status_output = capsys.readouterr().out
    assert "embedding_provider: local" in status_output

    assert run_rag_command(["build"], tmp_path) == 0
    build_output = capsys.readouterr().out
    assert "rebuilt: true" in build_output

    assert run_rag_command(["search", "status", "transition"], tmp_path) == 0
    search_output = capsys.readouterr().out
    assert "documents:" in search_output
    assert "knowledge" in search_output
