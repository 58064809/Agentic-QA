from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from harness.domain.models import StrictModel, normalize_workspace_id


class LogQueryRequest(StrictModel):
    workspace_id: str
    execution_id: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1)
    dataset_id: str | None = None
    environment: str = Field(min_length=1)
    api_service: str = Field(min_length=1)
    services: list[str] = Field(min_length=1)
    started_at: datetime
    completed_at: datetime
    max_entries: int = Field(ge=1, le=5000)
    trace_id: str | None = None
    request_id: str | None = None
    custom_ids: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_identity_and_window(self) -> LogQueryRequest:
        normalize_workspace_id(self.workspace_id)
        if self.completed_at < self.started_at:
            raise ValueError("log query completion cannot precede start")
        return self


class ProviderDiagnostic(StrictModel):
    code: str = Field(min_length=1)
    service: str | None = None
    detail: str = Field(min_length=1)


class NormalizedLogEntry(StrictModel):
    entry_id: str = Field(pattern=r"^LOG-[0-9]{6}$")
    timestamp: datetime | None = None
    service: str = Field(min_length=1)
    level: str = Field(min_length=1, max_length=32)
    message: str = Field(min_length=1, max_length=16_384)
    trace_id: str | None = Field(default=None, max_length=256)
    request_id: str | None = Field(default=None, max_length=256)
    exception_type: str | None = Field(default=None, max_length=256)
    source_ref: str = Field(min_length=1, max_length=512)


class LogQueryResult(StrictModel):
    status: Literal["success", "empty", "failed"]
    entries: list[NormalizedLogEntry] = Field(default_factory=list, max_length=5000)
    diagnostics: list[ProviderDiagnostic] = Field(default_factory=list)
    files_considered: int = Field(default=0, ge=0)
    bytes_read: int = Field(default=0, ge=0)


class LogEvidenceStats(StrictModel):
    entry_count: int = Field(ge=0)
    service_counts: dict[str, int] = Field(default_factory=dict)
    level_counts: dict[str, int] = Field(default_factory=dict)
    redaction_count: int = Field(ge=0)


class LogEvidenceBundle(StrictModel):
    schema_version: Literal["agentic-qa.log-evidence.v1"] = "agentic-qa.log-evidence.v1"
    collection_id: str = Field(min_length=1, max_length=128)
    execution_id: str = Field(min_length=1, max_length=128)
    case_id: str = Field(min_length=1)
    dataset_id: str | None = None
    execution_evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider: Literal["local-file", "loki"]
    provider_structure_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    query: LogQueryRequest
    status: Literal["success", "empty", "failed"]
    entries: list[NormalizedLogEntry] = Field(default_factory=list, max_length=5000)
    diagnostics: list[ProviderDiagnostic] = Field(default_factory=list)
    stats: LogEvidenceStats
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_content(self) -> LogEvidenceBundle:
        if self.stats.entry_count != len(self.entries):
            raise ValueError("log evidence stats do not match entries")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("log evidence content hash does not match")
        return self


class FailureLogCollection(StrictModel):
    collection_id: str
    case_id: str
    dataset_id: str | None = None
    log_collection_status: Literal["success", "empty", "failed"]
    collection_path: str
    log_evidence_path: str


class CollectFailureLogsCommand(StrictModel):
    workspace_id: str
    execution_id: str = Field(min_length=1, max_length=128)
    case_id: str | None = None

    @model_validator(mode="after")
    def validate_workspace(self) -> CollectFailureLogsCommand:
        normalize_workspace_id(self.workspace_id)
        return self


class CollectFailureLogsResult(StrictModel):
    schema_version: Literal["agentic-qa.harness.collect-failure-logs-result.v1"] = (
        "agentic-qa.harness.collect-failure-logs-result.v1"
    )
    workspace_id: str
    execution_id: str
    collections: list[FailureLogCollection]
    succeeded: int = Field(ge=0)
    empty: int = Field(ge=0)
    failed: int = Field(ge=0)
