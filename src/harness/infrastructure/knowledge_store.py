from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from harness.application.source import SourceBundle
from harness.domain.schemas.knowledge import (
    KnowledgeFreshness,
    KnowledgeMetadata,
    KnowledgeStatus,
    KnowledgeTrust,
)
from harness.domain.schemas.local_config import LocalEmbeddingConfig, LocalSystemDatabaseConfig
from harness.domain.security import contains_likely_secret

KNOWLEDGE_SCHEMA_VERSION = 3
KNOWLEDGE_SCHEMA = "agentic_qa_knowledge"
CHUNKER_VERSION = "source-aware-v1"
ADVISORY_LOCK_KEY = 0x4151414B
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
OPENAPI_OPERATION = re.compile(r"^\s{0,6}(get|put|post|delete|patch|head|options|trace):\s*$")
RECORD_START = re.compile(r"^\s*(?:case_id|bug_id|rule_id|schema_version):\s*", re.I)
LIST_ITEM = re.compile(r"^\s*(?:[-*+] |\d+[.)]\s+)")
TABLE_SEPARATOR = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    structure_kind: str
    locator: str
    content: str

    @property
    def content_sha256(self) -> str:
        return _sha256(self.content.encode())


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    raw = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    return f"{prefix}-{hashlib.sha256(raw).hexdigest()[:24]}"


class SourceAwareChunker:
    def __init__(self, max_characters: int = 4000) -> None:
        if not 500 <= max_characters <= 16000:
            raise ValueError("chunk max characters must be between 500 and 16000")
        self.max_characters = max_characters

    def chunk(self, source: str, text: str) -> list[ChunkDraft]:
        blocks = self._blocks(text)
        chunks: list[ChunkDraft] = []
        for kind, locator, content in blocks:
            if len(content) > self.max_characters:
                raise ValueError(
                    f"atomic {kind} block exceeds max chunk characters at {source}:{locator}"
                )
            if contains_likely_secret(content):
                continue
            chunks.append(
                ChunkDraft(
                    ordinal=len(chunks),
                    structure_kind=kind,
                    locator=locator,
                    content=content,
                )
            )
        return chunks

    def _blocks(self, text: str) -> list[tuple[str, str, str]]:
        lines = text.splitlines()
        blocks: list[tuple[str, str, str]] = []
        index = 0
        section = "document"
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                continue
            heading = HEADING.match(line)
            if heading:
                section = heading.group(2).strip()
                start = index
                index += 1
                while index < len(lines) and not HEADING.match(lines[index]):
                    index += 1
                self._append_section(blocks, section, start, lines[start:index])
                continue
            operation = OPENAPI_OPERATION.match(line)
            if operation:
                start = index
                base_indent = len(line) - len(line.lstrip())
                index += 1
                while index < len(lines):
                    candidate = lines[index]
                    indent = len(candidate) - len(candidate.lstrip())
                    if candidate.strip() and indent <= base_indent:
                        break
                    index += 1
                blocks.append(
                    ("openapi_operation", f"line:{start + 1}", "\n".join(lines[start:index]))
                )
                continue
            start = index
            index += 1
            while index < len(lines) and lines[index].strip() and not HEADING.match(lines[index]):
                index += 1
            kind = "record" if RECORD_START.match(line) else "paragraph"
            blocks.append((kind, f"line:{start + 1}", "\n".join(lines[start:index])))
        return blocks

    def _append_section(
        self,
        blocks: list[tuple[str, str, str]],
        title: str,
        start: int,
        lines: list[str],
    ) -> None:
        body = lines[1:]
        if len(body) >= 2 and any(TABLE_SEPARATOR.match(item) for item in body[:3]):
            separator = next(
                index for index, item in enumerate(body[:3]) if TABLE_SEPARATOR.match(item)
            )
            prefix = [lines[0], *body[: separator + 1]]
            rows = body[separator + 1 :]
            current = prefix.copy()
            part = 1
            for row in rows:
                candidate = "\n".join([*current, row])
                if len(candidate) > self.max_characters and len(current) > len(prefix):
                    blocks.append(("table", f"heading:{title}/table:{part}", "\n".join(current)))
                    part += 1
                    current = [*prefix, row]
                else:
                    current.append(row)
            blocks.append(("table", f"heading:{title}/table:{part}", "\n".join(current)))
            return
        if body and all(not item.strip() or LIST_ITEM.match(item) for item in body):
            blocks.append(("list_or_rule_block", f"heading:{title}", "\n".join(lines)))
            return
        blocks.append(("prd_section", f"heading:{title or start + 1}", "\n".join(lines)))


class DeterministicEmbeddingProvider:
    provider = "local-deterministic"
    model = "token-hash-v1"
    dimensions = 1536

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        tokens = re.findall(r"[\w\u4e00-\u9fff-]{2,}", text.casefold())
        for token in tokens:
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            values[index] += -1.0 if digest[4] & 1 else 1.0
        norm = sum(item * item for item in values) ** 0.5
        return [item / norm for item in values] if norm else values


class OpenAICompatibleEmbeddingProvider:
    dimensions = 1536

    def __init__(self, config: LocalEmbeddingConfig) -> None:
        if config.provider != "openai-compatible" or not config.base_url:
            raise ValueError("openai-compatible embedding configuration is required")
        self.provider = config.provider
        self.model = config.model
        self.base_url = config.base_url
        self.api_key_env = config.api_key_env

    def embed(self, texts: list[str]) -> list[list[float]]:
        api_key = os.environ.get(self.api_key_env, "").strip()
        if not api_key:
            raise RuntimeError(f"embedding API key is not set: {self.api_key_env}")
        from openai import OpenAI

        response = OpenAI(api_key=api_key, base_url=self.base_url).embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions,
        )
        vectors = [list(item.embedding) for item in response.data]
        if len(vectors) != len(texts) or any(len(item) != self.dimensions for item in vectors):
            raise ValueError("embedding provider returned an invalid batch or dimensions")
        return vectors


def embedding_provider_from_config(config: LocalEmbeddingConfig):
    if config.provider == "openai-compatible":
        return OpenAICompatibleEmbeddingProvider(config)
    return DeterministicEmbeddingProvider()


class PostgresKnowledgeStore:
    def __init__(self, config: LocalSystemDatabaseConfig) -> None:
        self.config = config

    @contextmanager
    def _connection(self):
        import psycopg

        with psycopg.connect(
            host=self.config.host,
            port=self.config.port,
            dbname=self.config.database,
            user=self.config.user,
            password=self.config.password,
            connect_timeout=self.config.connect_timeout_seconds,
        ) as connection:
            yield connection

    def migrate(self) -> int:
        try:
            with self._connection() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,))
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {KNOWLEDGE_SCHEMA}")
                for statement in _migration_statements():
                    cursor.execute(statement)
                cursor.execute(
                    f"""INSERT INTO {KNOWLEDGE_SCHEMA}.schema_version(version)
                    VALUES (%s) ON CONFLICT (version) DO NOTHING""",
                    (KNOWLEDGE_SCHEMA_VERSION,),
                )
        except Exception as exc:
            if getattr(exc, "sqlstate", None) in {"0A000", "58P01"} and "vector" in str(exc):
                raise RuntimeError(
                    "pgvector extension is unavailable in the configured system_database"
                ) from exc
            raise
        return KNOWLEDGE_SCHEMA_VERSION

    def index_source_bundle(
        self,
        workspace_id: str,
        run_id: str,
        bundle: SourceBundle,
        *,
        max_chunk_characters: int = 4000,
        embedding_provider: Any | None = None,
        trust: KnowledgeTrust = KnowledgeTrust.CURRENT_SOURCE,
        trust_resolver: Callable[[Any], KnowledgeTrust] | None = None,
        freshness: KnowledgeFreshness = KnowledgeFreshness.CURRENT,
    ) -> dict[str, int]:
        provider = embedding_provider or DeterministicEmbeddingProvider()
        chunker = SourceAwareChunker(max_chunk_characters)
        indexed = 0
        embedded = 0
        self.migrate()
        with self._connection() as connection, connection.cursor() as cursor:
            for document in bundle.readable_documents:
                document_trust = trust_resolver(document) if trust_resolver else trust
                source_hash = document.raw_sha256 or document.parsed_sha256
                if not source_hash:
                    continue
                document_id = _stable_id("DOC", workspace_id, document.path)
                version_id = _stable_id("VER", document_id, source_hash, run_id)
                metadata = KnowledgeMetadata(
                    workspace_id=workspace_id,
                    project_key=workspace_id,
                    document_type=_document_type(document.path),
                    freshness=freshness,
                    trust=document_trust,
                    run_id=run_id,
                )
                cursor.execute(
                    f"""INSERT INTO {KNOWLEDGE_SCHEMA}.document
                    (document_id, workspace_id, project_key, source_identity, document_type,
                     business_module,environment)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (document_id) DO NOTHING""",
                    (
                        document_id,
                        workspace_id,
                        workspace_id,
                        document.path,
                        metadata.document_type,
                        metadata.business_module,
                        metadata.environment,
                    ),
                )
                cursor.execute(
                    f"""SELECT coalesce(max(version_number),0)+1
                    FROM {KNOWLEDGE_SCHEMA}.document_version WHERE document_id=%s""",
                    (document_id,),
                )
                version_number = cursor.fetchone()[0]
                cursor.execute(
                    f"""INSERT INTO {KNOWLEDGE_SCHEMA}.document_version
                    (version_id, document_id, workspace_id, run_id, source_sha256, version_number,
                     freshness, trust)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (version_id) DO NOTHING""",
                    (
                        version_id,
                        document_id,
                        workspace_id,
                        metadata.run_id,
                        source_hash,
                        version_number,
                        metadata.freshness.value,
                        metadata.trust.value,
                    ),
                )
                inserted_version = cursor.rowcount == 1
                drafts = chunker.chunk(document.path, document.text or "")
                missing: list[ChunkDraft] = []
                for draft in drafts:
                    cursor.execute(
                        f"""SELECT embedding FROM {KNOWLEDGE_SCHEMA}.embedding_cache
                        WHERE provider=%s AND model=%s AND dimensions=%s AND chunk_sha256=%s""",
                        (
                            provider.provider,
                            provider.model,
                            provider.dimensions,
                            draft.content_sha256,
                        ),
                    )
                    if cursor.fetchone() is None:
                        missing.append(draft)
                vectors = provider.embed([item.content for item in missing])
                for draft, vector in zip(missing, vectors, strict=True):
                    cursor.execute(
                        f"""INSERT INTO {KNOWLEDGE_SCHEMA}.embedding_cache
                        (provider,model,dimensions,chunk_sha256,embedding)
                        VALUES (%s,%s,%s,%s,%s::vector) ON CONFLICT DO NOTHING""",
                        (
                            provider.provider,
                            provider.model,
                            provider.dimensions,
                            draft.content_sha256,
                            _vector_literal(vector),
                        ),
                    )
                    embedded += 1
                for draft in drafts:
                    chunk_id = _stable_id(
                        "CHUNK", version_id, CHUNKER_VERSION, draft.locator, draft.content_sha256
                    )
                    cursor.execute(
                        f"""INSERT INTO {KNOWLEDGE_SCHEMA}.chunk
                        (chunk_id,version_id,document_id,workspace_id,ordinal,structure_kind,locator,
                         content,search_content,content_sha256,embedding_provider,embedding_model,
                         embedding_dimensions)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (chunk_id) DO NOTHING""",
                        (
                            chunk_id,
                            version_id,
                            document_id,
                            workspace_id,
                            draft.ordinal,
                            draft.structure_kind,
                            draft.locator,
                            draft.content,
                            _search_content(draft.content),
                            draft.content_sha256,
                            provider.provider,
                            provider.model,
                            provider.dimensions,
                        ),
                    )
                    indexed += cursor.rowcount
                    cursor.execute(
                        f"""INSERT INTO {KNOWLEDGE_SCHEMA}.chunk_embedding
                        (chunk_id,provider,model,dimensions,chunk_sha256)
                        VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (
                            chunk_id,
                            provider.provider,
                            provider.model,
                            provider.dimensions,
                            draft.content_sha256,
                        ),
                    )
                if inserted_version and freshness == KnowledgeFreshness.HISTORICAL:
                    cursor.execute(
                        f"""UPDATE {KNOWLEDGE_SCHEMA}.document_version
                        SET freshness='superseded'
                        WHERE document_id=%s AND version_id<>%s AND freshness='historical'""",
                        (document_id, version_id),
                    )
        return {
            "documents": len(bundle.readable_documents),
            "chunks": indexed,
            "embedded": embedded,
        }

    def status(self, workspace_id: str) -> KnowledgeStatus:
        self.migrate()
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT count(*) FROM {KNOWLEDGE_SCHEMA}.document WHERE workspace_id=%s",
                (workspace_id,),
            )
            documents = cursor.fetchone()[0]
            cursor.execute(
                f"SELECT count(*) FROM {KNOWLEDGE_SCHEMA}.chunk WHERE workspace_id=%s",
                (workspace_id,),
            )
            chunks = cursor.fetchone()[0]
            cursor.execute(
                f"""SELECT status,count(*) FROM {KNOWLEDGE_SCHEMA}.publication_outbox
                WHERE workspace_id=%s GROUP BY status""",
                (workspace_id,),
            )
            outbox = dict(cursor.fetchall())
        return KnowledgeStatus(
            workspace_id=workspace_id,
            schema_version_applied=KNOWLEDGE_SCHEMA_VERSION,
            document_count=documents,
            chunk_count=chunks,
            pending_publications=outbox.get("pending", 0),
            failed_publications=outbox.get("failed", 0),
        )

    def delete_document(self, workspace_id: str, document_id: str) -> None:
        self.migrate()
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""UPDATE {KNOWLEDGE_SCHEMA}.document SET deleted_at=now()
                WHERE workspace_id=%s AND document_id=%s""",
                (workspace_id, document_id),
            )
            if cursor.rowcount != 1:
                raise FileNotFoundError("knowledge document does not exist in workspace")
            cursor.execute(
                f"DELETE FROM {KNOWLEDGE_SCHEMA}.chunk WHERE workspace_id=%s AND document_id=%s",
                (workspace_id, document_id),
            )
            cursor.execute(
                f"""DELETE FROM {KNOWLEDGE_SCHEMA}.embedding_cache cache
                WHERE NOT EXISTS (
                    SELECT 1 FROM {KNOWLEDGE_SCHEMA}.chunk_embedding association
                    WHERE association.chunk_sha256=cache.chunk_sha256
                    AND association.provider=cache.provider
                    AND association.model=cache.model
                    AND association.dimensions=cache.dimensions)"""
            )

    def enqueue_publication(self, publication_id: str, workspace_id: str, run_id: str) -> None:
        self.migrate()
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""INSERT INTO {KNOWLEDGE_SCHEMA}.publication_outbox
                (publication_id,workspace_id,run_id,status)
                VALUES (%s,%s,%s,'pending') ON CONFLICT (publication_id) DO NOTHING""",
                (publication_id, workspace_id, run_id),
            )

    def mark_publication(
        self, publication_id: str, *, status: str, error: str | None = None
    ) -> None:
        if status not in {"completed", "failed"}:
            raise ValueError("publication outbox status must be completed or failed")
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""UPDATE {KNOWLEDGE_SCHEMA}.publication_outbox
                SET status=%s,attempts=attempts+1,error=%s,updated_at=now()
                WHERE publication_id=%s""",
                (status, error, publication_id),
            )


def _document_type(path: str) -> str:
    lowered = path.casefold()
    if "openapi" in lowered or "swagger" in lowered:
        return "openapi"
    if "bug" in lowered:
        return "bug"
    if "test" in lowered or "case" in lowered:
        return "testcase"
    return "requirement"


def _vector_literal(vector: Iterable[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def _search_content(content: str) -> str:
    cjk = [item for item in re.findall(r"[\u4e00-\u9fff]{2,}", content)]
    bigrams = [value[index : index + 2] for value in cjk for index in range(len(value) - 1)]
    return content + (" " + " ".join(bigrams) if bigrams else "")


def _migration_statements() -> list[str]:
    prefix = KNOWLEDGE_SCHEMA
    return [
        f"""CREATE TABLE IF NOT EXISTS {prefix}.schema_version (
        version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}.document (
        document_id text PRIMARY KEY, workspace_id text NOT NULL, project_key text NOT NULL,
        source_identity text NOT NULL, document_type text NOT NULL,
        business_module text, environment text, deleted_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(), CHECK (workspace_id=project_key),
        UNIQUE(workspace_id,source_identity))""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}.document_version (
        version_id text PRIMARY KEY,
        document_id text NOT NULL REFERENCES {prefix}.document(document_id),
        workspace_id text NOT NULL, run_id text, source_sha256 text NOT NULL,
        version_number integer NOT NULL,
        freshness text NOT NULL
            CHECK(freshness IN ('current','historical','superseded','deprecated')),
        trust text NOT NULL
            CHECK(trust IN ('current_source','reviewed_requirement','reviewed_contract',
                            'reviewed_test_asset','reviewed_bug','reviewed_asset',
                            'execution_evidence','reference_only')),
        created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(document_id,source_sha256,run_id))""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}.embedding_cache (
        provider text NOT NULL, model text NOT NULL, dimensions integer NOT NULL,
        chunk_sha256 text NOT NULL, embedding vector(1536) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY(provider,model,dimensions,chunk_sha256))""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}.chunk (
        chunk_id text PRIMARY KEY,
        version_id text NOT NULL REFERENCES {prefix}.document_version(version_id),
        document_id text NOT NULL REFERENCES {prefix}.document(document_id),
        workspace_id text NOT NULL,
        ordinal integer NOT NULL, structure_kind text NOT NULL, locator text NOT NULL,
        content text NOT NULL, search_content text NOT NULL, content_sha256 text NOT NULL,
        search tsvector GENERATED ALWAYS AS (to_tsvector('simple', search_content)) STORED,
        embedding_provider text NOT NULL,
        embedding_model text NOT NULL, embedding_dimensions integer NOT NULL,
        UNIQUE(version_id,ordinal))""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}.chunk_embedding (
        chunk_id text NOT NULL REFERENCES {prefix}.chunk(chunk_id) ON DELETE CASCADE,
        provider text NOT NULL, model text NOT NULL, dimensions integer NOT NULL,
        chunk_sha256 text NOT NULL,
        PRIMARY KEY(chunk_id,provider,model,dimensions))""",
        f"""CREATE INDEX IF NOT EXISTS chunk_workspace_idx
        ON {prefix}.chunk(workspace_id,document_id)""",
        f"CREATE INDEX IF NOT EXISTS chunk_fts_idx ON {prefix}.chunk USING gin(search)",
        f"""INSERT INTO {prefix}.chunk_embedding
        (chunk_id,provider,model,dimensions,chunk_sha256)
        SELECT chunk_id,embedding_provider,embedding_model,embedding_dimensions,content_sha256
        FROM {prefix}.chunk ON CONFLICT DO NOTHING""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}.retrieval_audit (
        retrieval_id text PRIMARY KEY, workspace_id text NOT NULL, run_id text, query text NOT NULL,
        purpose text NOT NULL, filters jsonb NOT NULL, strategy text NOT NULL,
        index_version text NOT NULL, embedding_index_identity text NOT NULL,
        candidate_count integer NOT NULL, selected_chunk_ids jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now())""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}.retrieval_item (
        retrieval_id text NOT NULL REFERENCES {prefix}.retrieval_audit(retrieval_id),
        chunk_id text NOT NULL,
        lexical_rank integer, lexical_score double precision, vector_rank integer,
        vector_score double precision, fused_score double precision NOT NULL,
        rerank_score double precision,
        PRIMARY KEY(retrieval_id,chunk_id))""",
        f"""CREATE TABLE IF NOT EXISTS {prefix}.publication_outbox (
        publication_id text PRIMARY KEY, workspace_id text NOT NULL, run_id text NOT NULL,
        status text NOT NULL CHECK(status IN ('pending','completed','failed')),
        attempts integer NOT NULL DEFAULT 0, error text,
        updated_at timestamptz NOT NULL DEFAULT now())""",
        f"ALTER TABLE {prefix}.document ADD COLUMN IF NOT EXISTS business_module text",
        f"ALTER TABLE {prefix}.document ADD COLUMN IF NOT EXISTS environment text",
        f"""ALTER TABLE {prefix}.document_version
        ADD COLUMN IF NOT EXISTS version_number integer NOT NULL DEFAULT 1""",
        f"""DO $$ DECLARE constraint_name text; BEGIN
        SELECT c.conname INTO constraint_name FROM pg_constraint c
        JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace
        WHERE n.nspname='{prefix}' AND t.relname='document_version'
          AND c.contype='c' AND pg_get_constraintdef(c.oid) LIKE '%trust%';
        IF constraint_name IS NOT NULL THEN
            EXECUTE format('ALTER TABLE {prefix}.document_version DROP CONSTRAINT %I',
                           constraint_name);
        END IF;
        ALTER TABLE {prefix}.document_version ADD CONSTRAINT document_version_trust_check
          CHECK(trust IN ('current_source','reviewed_requirement','reviewed_contract',
                          'reviewed_test_asset','reviewed_bug','reviewed_asset',
                          'execution_evidence','reference_only'));
        END $$""",
        f"""ALTER TABLE {prefix}.retrieval_audit
        ADD COLUMN IF NOT EXISTS embedding_index_identity text""",
        f"""UPDATE {prefix}.retrieval_audit SET embedding_index_identity=index_version
        WHERE embedding_index_identity IS NULL""",
        f"""ALTER TABLE {prefix}.retrieval_audit
        ALTER COLUMN embedding_index_identity SET NOT NULL""",
        f"ALTER TABLE {prefix}.chunk ADD COLUMN IF NOT EXISTS search_content text",
        f"UPDATE {prefix}.chunk SET search_content=content WHERE search_content IS NULL",
        f"ALTER TABLE {prefix}.chunk ALTER COLUMN search_content SET NOT NULL",
        f"""DO $$ BEGIN
        IF EXISTS (
            SELECT 1 FROM pg_attribute a
            JOIN pg_class c ON c.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
            WHERE n.nspname='{prefix}' AND c.relname='chunk' AND a.attname='search'
              AND pg_get_expr(d.adbin,d.adrelid) NOT LIKE '%search_content%'
        ) THEN
            DROP INDEX IF EXISTS {prefix}.chunk_fts_idx;
            ALTER TABLE {prefix}.chunk DROP COLUMN search;
            ALTER TABLE {prefix}.chunk ADD COLUMN search tsvector
              GENERATED ALWAYS AS (to_tsvector('simple', search_content)) STORED;
        END IF;
        END $$""",
        f"""ALTER TABLE {prefix}.chunk ADD COLUMN IF NOT EXISTS search tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', search_content)) STORED""",
        f"CREATE INDEX IF NOT EXISTS chunk_fts_idx ON {prefix}.chunk USING gin(search)",
    ]
