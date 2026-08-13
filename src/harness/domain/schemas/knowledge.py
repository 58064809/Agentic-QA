from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from harness.domain.models import StrictModel

SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class KnowledgeFreshness(str, Enum):
    CURRENT = "current"
    HISTORICAL = "historical"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"


class KnowledgeTrust(str, Enum):
    CURRENT_SOURCE = "current_source"
    REVIEWED_REQUIREMENT = "reviewed_requirement"
    REVIEWED_ASSET = "reviewed_asset"
    EXECUTION_EVIDENCE = "execution_evidence"
    REFERENCE_ONLY = "reference_only"


class KnowledgeMetadata(StrictModel):
    workspace_id: str = Field(min_length=1)
    project_key: str = Field(min_length=1)
    document_type: str = Field(min_length=1)
    business_module: str | None = None
    environment: str | None = None
    freshness: KnowledgeFreshness
    trust: KnowledgeTrust
    run_id: str | None = None

    @model_validator(mode="after")
    def enforce_initial_project_boundary(self) -> KnowledgeMetadata:
        if self.project_key != self.workspace_id:
            raise ValueError("project_key must equal workspace_id in the initial knowledge model")
        if self.trust == KnowledgeTrust.CURRENT_SOURCE and not self.run_id:
            raise ValueError("current_source knowledge requires run_id")
        return self


class KnowledgeDocument(StrictModel):
    schema_version: Literal["agentic-qa.knowledge-document.v1"] = "agentic-qa.knowledge-document.v1"
    document_id: str = Field(min_length=1)
    source_identity: str = Field(min_length=1)
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    version: int = Field(ge=1)
    metadata: KnowledgeMetadata
    created_at: str = Field(min_length=1)
    deleted: bool = False


class KnowledgeChunk(StrictModel):
    schema_version: Literal["agentic-qa.knowledge-chunk.v1"] = "agentic-qa.knowledge-chunk.v1"
    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version: int = Field(ge=1)
    ordinal: int = Field(ge=0)
    structure_kind: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    content: str = Field(min_length=1)
    content_sha256: str = Field(pattern=SHA256_PATTERN)
    embedding_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    metadata: KnowledgeMetadata


class RetrievalFilters(StrictModel):
    source_types: list[str] = Field(default_factory=list)
    document_versions: list[int] = Field(default_factory=list)
    business_modules: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    freshness: list[KnowledgeFreshness] = Field(
        default_factory=lambda: [KnowledgeFreshness.CURRENT, KnowledgeFreshness.HISTORICAL]
    )
    trust: list[KnowledgeTrust] = Field(default_factory=list)

    @field_validator(
        "source_types",
        "business_modules",
        "environments",
        "document_versions",
        "freshness",
        "trust",
    )
    @classmethod
    def require_unique_values(cls, values: list) -> list:
        if len(values) != len(set(values)):
            raise ValueError("retrieval filter values must be unique")
        return values


class RetrievalQuery(StrictModel):
    schema_version: Literal["agentic-qa.retrieval-query.v1"] = "agentic-qa.retrieval-query.v1"
    workspace_id: str = Field(min_length=1)
    run_id: str | None = None
    query: str = Field(min_length=1)
    purpose: Literal["requirement", "impact", "risk", "regression", "reference"]
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    max_chunks: int = Field(default=10, ge=1, le=20)


class RetrievalCandidate(StrictModel):
    chunk_id: str
    document_id: str
    source_identity: str
    chunk_ordinal: int = Field(ge=0)
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    content: str
    lexical_rank: int | None = Field(default=None, ge=1)
    lexical_score: float | None = Field(default=None, ge=0)
    vector_rank: int | None = Field(default=None, ge=1)
    vector_score: float | None = Field(default=None, ge=-1, le=1)
    fused_score: float = Field(ge=0)
    rerank_score: float | None = None
    metadata: KnowledgeMetadata


class RetrievalProvenance(StrictModel):
    retrieval_id: str = Field(min_length=1)
    strategy: Literal["postgres-hybrid-rrf", "run-local-hybrid-rrf"]
    index_version: str = Field(min_length=1)
    candidate_count: int = Field(ge=0)
    selected_chunk_ids: list[str]
    reranker: Literal["none", "model"]
    filters_sha256: str = Field(pattern=SHA256_PATTERN)


class RetrievalResult(StrictModel):
    schema_version: Literal["agentic-qa.retrieval-result.v1"] = "agentic-qa.retrieval-result.v1"
    query: RetrievalQuery
    chunks: list[RetrievalCandidate]
    provenance: RetrievalProvenance
    content_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_content_hash(self) -> RetrievalResult:
        if len(self.chunks) > self.query.max_chunks:
            raise ValueError("retrieval result exceeds requested max_chunks")
        if self.provenance.selected_chunk_ids != [item.chunk_id for item in self.chunks]:
            raise ValueError("retrieval provenance selected chunks differ from result")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        if digest != self.content_sha256:
            raise ValueError("retrieval result content hash does not match")
        return self


class KnowledgeStatus(StrictModel):
    schema_version: Literal["agentic-qa.knowledge-status.v1"] = "agentic-qa.knowledge-status.v1"
    workspace_id: str
    schema_version_applied: int = Field(ge=0)
    document_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    pending_publications: int = Field(ge=0)
    failed_publications: int = Field(ge=0)


class KnowledgeMigrateResult(StrictModel):
    schema_version: Literal["agentic-qa.knowledge-migrate-result.v1"] = (
        "agentic-qa.knowledge-migrate-result.v1"
    )
    applied_version: int = Field(ge=1)


class KnowledgeIndexRunCommand(StrictModel):
    workspace_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)


class KnowledgeIndexResult(StrictModel):
    schema_version: Literal["agentic-qa.knowledge-index-result.v1"] = (
        "agentic-qa.knowledge-index-result.v1"
    )
    workspace_id: str
    run_id: str
    documents: int = Field(ge=0)
    chunks: int = Field(ge=0)
    embedded: int = Field(ge=0)
    status: Literal["completed", "already_indexed"]


class KnowledgeReindexCommand(StrictModel):
    workspace_id: str = Field(min_length=1)
    published: bool = True

    @field_validator("published")
    @classmethod
    def require_published(cls, value: bool) -> bool:
        if not value:
            raise ValueError("knowledge reindex only accepts reviewed published history")
        return value


class KnowledgeReindexResult(StrictModel):
    schema_version: Literal["agentic-qa.knowledge-reindex-result.v1"] = (
        "agentic-qa.knowledge-reindex-result.v1"
    )
    workspace_id: str
    indexed_runs: list[str]
    indexed_executions: list[str] = Field(default_factory=list)


class KnowledgeDeleteCommand(StrictModel):
    workspace_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)


class KnowledgeDeleteResult(StrictModel):
    schema_version: Literal["agentic-qa.knowledge-delete-result.v1"] = (
        "agentic-qa.knowledge-delete-result.v1"
    )
    workspace_id: str
    document_id: str
    tombstoned: Literal[True] = True


class RetrievalEvalMetrics(StrictModel):
    schema_version: Literal["agentic-qa.retrieval-eval-metrics.v1"] = (
        "agentic-qa.retrieval-eval-metrics.v1"
    )
    query_count: int = Field(ge=1)
    recall_at_10: float = Field(ge=0, le=1)
    mrr: float = Field(ge=0, le=1)
    source_hit_rate: float = Field(ge=0, le=1)
    wrong_source_rate: float = Field(ge=0, le=1)
    superseded_leakage: int = Field(ge=0)
    cross_workspace_leakage: int = Field(ge=0)
    passed: bool
