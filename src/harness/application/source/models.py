from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceIssueSeverity(str, Enum):
    WARNING = "warning"
    BLOCKER = "blocker"


class SourceCompleteness(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    EMPTY = "empty"


class SourceIssue(FrozenModel):
    code: str = Field(min_length=1)
    severity: SourceIssueSeverity = SourceIssueSeverity.WARNING
    path: str | None = None
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class SourceIngestionLimits(FrozenModel):
    max_files: int = Field(default=256, ge=1)
    max_path_bytes: int = Field(default=1024, ge=64)
    max_parse_bytes: int = Field(default=16 * 1024 * 1024, ge=1024)
    max_hash_bytes: int = Field(default=64 * 1024 * 1024, ge=1024)
    max_total_hash_bytes: int = Field(default=64 * 1024 * 1024, ge=1024)
    max_parsed_characters: int = Field(default=100_000, ge=1)
    max_file_bytes: int | None = Field(default=None, ge=1024)
    max_total_bytes: int | None = Field(default=None, ge=1024)


class SourceDocument(FrozenModel):
    path: str = Field(min_length=1)
    raw_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    parsed_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    byte_size: int | None = Field(default=None, ge=0)
    text: str | None = None
    completeness: SourceCompleteness
    truncated: bool = False
    issues: tuple[SourceIssue, ...] = ()

    @model_validator(mode="after")
    def validate_snapshot_identity(self) -> SourceDocument:
        if self.completeness == SourceCompleteness.UNAVAILABLE and self.parsed_sha256 is not None:
            raise ValueError("unavailable source document cannot have parsed_sha256")
        if self.completeness in {SourceCompleteness.COMPLETE, SourceCompleteness.PARTIAL}:
            if self.parsed_sha256 is None:
                raise ValueError("complete or partial source document requires parsed_sha256")
        if self.text is not None and self.parsed_sha256 is None:
            raise ValueError("source document text requires parsed_sha256")
        return self


class SourceBundle(FrozenModel):
    schema_version: Literal["agentic-qa.harness.source-bundle.v2"] = (
        "agentic-qa.harness.source-bundle.v2"
    )
    parser_version: str = Field(min_length=1)
    limits: SourceIngestionLimits
    documents: tuple[SourceDocument, ...] = ()
    issues: tuple[SourceIssue, ...] = ()
    completeness: SourceCompleteness
    bundle_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @property
    def readable_documents(self) -> tuple[SourceDocument, ...]:
        return tuple(document for document in self.documents if document.text is not None)

    @property
    def corpus(self) -> str:
        return "\n".join(document.text or "" for document in self.documents)
