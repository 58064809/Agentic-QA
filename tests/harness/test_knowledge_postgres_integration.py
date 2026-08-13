from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from harness.application.source import (
    SourceBundle,
    SourceCompleteness,
    SourceDocument,
    SourceIngestionLimits,
)
from harness.domain.schemas.knowledge import RetrievalQuery
from harness.infrastructure.knowledge_store import KNOWLEDGE_SCHEMA, PostgresKnowledgeStore
from harness.infrastructure.local_config import FilesystemLocalConfigLoader
from harness.infrastructure.rag.provider import PostgresHybridRetriever


@pytest.mark.postgres
def test_pgvector_incremental_index_hybrid_retrieval_and_workspace_isolation() -> None:
    config = FilesystemLocalConfigLoader(Path.cwd()).load_required().system_database
    if config.password == "local-validation-only":
        pytest.skip("system_database.password is still the local placeholder")
    store = PostgresKnowledgeStore(config)
    workspace_id = f"knowledge-integration-{uuid4().hex}"
    other_workspace = f"{workspace_id}-other"
    run_id = "run-1"
    content = "Account login is locked after five consecutive failed attempts."
    digest = "sha256:" + hashlib.sha256(content.encode()).hexdigest()
    bundle = SourceBundle(
        parser_version="integration-v1",
        limits=SourceIngestionLimits(),
        documents=(
            SourceDocument(
                path="sources/login.md",
                raw_sha256=digest,
                parsed_sha256=digest,
                byte_size=len(content.encode()),
                text=content,
                completeness=SourceCompleteness.COMPLETE,
            ),
        ),
        completeness=SourceCompleteness.COMPLETE,
        bundle_hash=digest,
    )
    migrated = False
    try:
        try:
            store.migrate()
            migrated = True
        except RuntimeError as exc:
            if "pgvector extension is unavailable" in str(exc):
                pytest.skip(str(exc))
            raise
        first = store.index_source_bundle(workspace_id, run_id, bundle)
        second = store.index_source_bundle(workspace_id, run_id, bundle)
        store.index_source_bundle(other_workspace, run_id, bundle)

        assert first["chunks"] == first["embedded"] == 1
        assert second["chunks"] == second["embedded"] == 0
        result = PostgresHybridRetriever(store).retrieve(
            RetrievalQuery(
                workspace_id=workspace_id,
                run_id=run_id,
                query="login locked five failures",
                purpose="requirement",
            )
        )
        assert result.chunks
        assert all(item.metadata.workspace_id == workspace_id for item in result.chunks)
        assert result.chunks[0].source_identity == "sources/login.md"
    finally:
        if migrated:
            _purge_test_workspaces(store, [workspace_id, other_workspace])


def _purge_test_workspaces(store: PostgresKnowledgeStore, workspace_ids: list[str]) -> None:
    with store._connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            f"""DELETE FROM {KNOWLEDGE_SCHEMA}.retrieval_item WHERE retrieval_id IN
            (SELECT retrieval_id FROM {KNOWLEDGE_SCHEMA}.retrieval_audit
             WHERE workspace_id = ANY(%s))""",
            (workspace_ids,),
        )
        for table in (
            "retrieval_audit",
            "chunk",
            "document_version",
            "document",
            "publication_outbox",
        ):
            cursor.execute(
                f"DELETE FROM {KNOWLEDGE_SCHEMA}.{table} WHERE workspace_id = ANY(%s)",
                (workspace_ids,),
            )
        cursor.execute(
            f"""DELETE FROM {KNOWLEDGE_SCHEMA}.embedding_cache e WHERE NOT EXISTS
            (SELECT 1 FROM {KNOWLEDGE_SCHEMA}.chunk c
             WHERE c.content_sha256=e.chunk_sha256 AND c.embedding_provider=e.provider
               AND c.embedding_model=e.model AND c.embedding_dimensions=e.dimensions)"""
        )
