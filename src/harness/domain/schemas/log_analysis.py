from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from harness.domain.models import StrictModel, normalize_workspace_id


class LogSignal(StrictModel):
    signal_id: str = Field(pattern=r"^SIGNAL-[0-9]{4}$")
    category: Literal["exception", "http", "database", "rpc", "redis", "mq", "network", "timeout"]
    service: str
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    exception_type: str | None = None
    normalized_message: str
    top_frames: list[str] = Field(default_factory=list, max_length=10)
    occurrence_count: int = Field(ge=1)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    sample_refs: list[str] = Field(min_length=1, max_length=10)


class FailureTimelineEvent(StrictModel):
    reference: str
    timestamp: datetime | None = None
    source: Literal["execution", "log"]
    service: str | None = None
    event: str


class LogAnalysis(StrictModel):
    schema_version: Literal["agentic-qa.log-analysis.v1"] = "agentic-qa.log-analysis.v1"
    collection_id: str
    execution_id: str
    case_id: str
    dataset_id: str | None = None
    log_evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    signals: list[LogSignal] = Field(default_factory=list, max_length=300)
    timeline: list[FailureTimelineEvent] = Field(default_factory=list, max_length=5002)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_hash(self) -> LogAnalysis:
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("log analysis content hash does not match")
        return self


class AnalyzeFailureCommand(StrictModel):
    workspace_id: str
    execution_id: str
    case_id: str | None = None
    collection_id: str | None = None

    @model_validator(mode="after")
    def validate_workspace(self) -> AnalyzeFailureCommand:
        normalize_workspace_id(self.workspace_id)
        return self


class FailureAnalysisItem(StrictModel):
    collection_id: str
    case_id: str
    dataset_id: str | None = None
    analysis_status: Literal["success", "empty", "failed"]
    log_analysis_path: str
    triage_status: Literal["not_started", "success", "insufficient_evidence", "failed"] = (
        "not_started"
    )
    failure_triage_path: str | None = None


class AnalyzeFailureResult(StrictModel):
    schema_version: Literal["agentic-qa.harness.analyze-failure-result.v1"] = (
        "agentic-qa.harness.analyze-failure-result.v1"
    )
    workspace_id: str
    execution_id: str
    analyses: list[FailureAnalysisItem]
