from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

API_CASES_SCHEMA_VERSION = "agentic-qa.api-cases.v1.1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(StrictModel):
    source_type: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    confidence: Literal["low", "medium", "high"]


class ApiRequest(StrictModel):
    method: str | None = None
    path: str | None = None
    headers: dict[str, Any] = Field(default_factory=dict)
    query: Any = Field(default_factory=dict)
    body: Any = Field(default_factory=dict)


class ApiAssertion(StrictModel):
    type: str = Field(min_length=1)
    expected: Any | None = None
    path: str | None = None


class ApiTestCase(StrictModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    priority: Literal["P0", "P1", "P2", "P3"]
    contract_status: Literal["missing", "pending_confirmation", "partial", "confirmed"]
    business_rule_refs: list[str]
    review_status: Literal["needs_human_review"]
    review_questions: list[str]
    source_refs: list[SourceRef] = Field(min_length=1)
    pending: list[str]
    request: ApiRequest
    assertions: list[ApiAssertion]
    variables: dict[str, Any]
    cleanup: list[Any]


class ApiTestCasesDraft(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Literal["agentic-qa.api-cases.v1.1"]
    artifact_type: Literal["api_automation_cases"]
    status: Literal["needs_human_review"]
    human_review_required: Literal[True]
    base_url_env: Literal["AGENTIC_QA_BASE_URL"]
    business_rules: list[Any] = Field(min_length=1)
    source_refs: list[SourceRef] = Field(min_length=1)
    cases: list[ApiTestCase] = Field(min_length=1)
    review_questions: list[str] = Field(min_length=1)
