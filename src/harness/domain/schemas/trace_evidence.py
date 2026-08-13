from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from harness.domain.models import StrictModel, normalize_workspace_id
from harness.domain.schemas.log_evidence import ProviderDiagnostic


class TraceQueryRequest(StrictModel):
    workspace_id: str
    execution_id: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1)
    dataset_id: str | None = None
    environment: str = Field(min_length=1)
    trace_id: str = Field(min_length=1, max_length=256)
    started_at: datetime
    completed_at: datetime
    max_spans: int = Field(default=1000, ge=1, le=5000)

    @model_validator(mode="after")
    def validate_identity_and_window(self) -> TraceQueryRequest:
        normalize_workspace_id(self.workspace_id)
        if self.completed_at < self.started_at:
            raise ValueError("trace query completion cannot precede start")
        return self


class ProviderTraceSpan(StrictModel):
    trace_id: str = Field(min_length=1, max_length=256)
    span_id: str = Field(min_length=1, max_length=128)
    parent_span_id: str | None = Field(default=None, max_length=128)
    service: str = Field(min_length=1, max_length=256)
    operation: str = Field(min_length=1, max_length=512)
    span_kind: Literal["server", "client", "producer", "consumer", "internal", "unknown"]
    started_at: datetime
    ended_at: datetime | None = None
    status: Literal["ok", "error", "unset"] = "unset"
    error_type: str | None = Field(default=None, max_length=256)
    error_message_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    http_method: str | None = Field(default=None, max_length=16)
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    rpc_system: str | None = Field(default=None, max_length=128)
    db_system: str | None = Field(default=None, max_length=128)
    peer_service: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_time(self) -> ProviderTraceSpan:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("trace span end cannot precede start")
        return self


class TraceQueryResult(StrictModel):
    status: Literal["success", "not_found", "failed"]
    provider: Literal["local-file", "tempo"]
    trace_id: str = Field(min_length=1, max_length=256)
    spans: list[ProviderTraceSpan] = Field(default_factory=list, max_length=5000)
    diagnostics: list[ProviderDiagnostic] = Field(default_factory=list)


class NormalizedTraceSpan(ProviderTraceSpan):
    evidence_ref: str = Field(pattern=r"^TRACE-[0-9]{6}$")
    duration_ms: float | None = Field(default=None, ge=0)


class TraceEvidenceBundle(StrictModel):
    schema_version: Literal["agentic-qa.trace-evidence.v1"] = "agentic-qa.trace-evidence.v1"
    collection_id: str = Field(min_length=1, max_length=128)
    execution_id: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1)
    dataset_id: str | None = None
    trace_id: str = Field(min_length=1, max_length=256)
    execution_evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider: Literal["local-file", "tempo"]
    provider_structure_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    query: TraceQueryRequest
    status: Literal["success", "not_found", "failed"]
    spans: list[NormalizedTraceSpan] = Field(default_factory=list, max_length=5000)
    root_span_ref: str | None = Field(default=None, pattern=r"^TRACE-[0-9]{6}$")
    diagnostics: list[ProviderDiagnostic] = Field(default_factory=list)
    created_at: datetime
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_content(self) -> TraceEvidenceBundle:
        refs = {span.evidence_ref for span in self.spans}
        if len(refs) != len(self.spans):
            raise ValueError("trace evidence references must be unique")
        if self.root_span_ref is not None and self.root_span_ref not in refs:
            raise ValueError("trace evidence root reference is unresolved")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("trace evidence content hash does not match")
        return self
