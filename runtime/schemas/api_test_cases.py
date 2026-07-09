from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

API_CASES_SCHEMA_VERSION = "agentic-qa.api-cases.v1"


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_type: str | None = None
    source_path: str | None = None
    chunk_id: str | None = None
    locator: str | None = None
    summary: str | None = None
    confidence: str | None = None


class ApiTestCase(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    title: str | None = None
    contract_status: str | None = None
    business_rule_refs: list[Any] | None = None
    review_status: str | None = None
    review_questions: list[Any] | None = None
    source_refs: list[SourceRef] | None = None
    pending: list[Any] | None = None
    method: str | None = None
    path: str | None = None
    request: dict[str, Any] | None = None
    expected: dict[str, Any] | None = None


class ApiTestCasesDraft(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str | None = None
    status: str | None = None
    human_review_required: bool | None = None
    base_url_env: str | None = None
    business_rules: list[Any] | None = None
    source_refs: list[SourceRef] | None = None
    cases: list[ApiTestCase] | None = None
