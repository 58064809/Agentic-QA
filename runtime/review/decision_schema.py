from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ArtifactTarget = Literal[
    "testcases",
    "requirement_analysis",
    "api_test_draft",
    "ui_test_draft",
    "qa_report",
    "all",
]


class ReviewIntent(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REVISE = "revise"
    HOLD = "hold"
    SHOW_DIFF = "show_diff"
    CLARIFY = "clarify"


class ReviewDecision(BaseModel):
    intent: ReviewIntent
    target_artifact: ArtifactTarget | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str
    revision_request: str | None = None
    requires_confirmation: bool = False

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("reason 不能为空")
        return reason

    @field_validator("revision_request")
    @classmethod
    def normalize_revision_request(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
