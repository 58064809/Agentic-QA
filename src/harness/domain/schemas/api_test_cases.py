from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

API_CASES_SCHEMA_VERSION = "agentic-qa.api-cases.v1.1"
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}


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

    @field_validator("method")
    @classmethod
    def validate_method(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.upper()
        if normalized not in HTTP_METHODS:
            raise ValueError(f"unsupported HTTP method: {value}")
        return normalized

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/"):
            raise ValueError("API request path must start with '/'")
        return value


class ConfirmedApiRequest(ApiRequest):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"]
    path: str = Field(min_length=1)


class UnconfirmedApiRequest(ApiRequest):
    method: Literal[None] = None
    path: Literal[None] = None


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

    @model_validator(mode="after")
    def validate_contract_evidence(self) -> ApiTestCase:
        if self.contract_status == "confirmed":
            if not self.request.method or not self.request.path:
                raise ValueError("confirmed API case requires request.method and request.path")
            if not any(
                reference.source_type == "openapi" and reference.confidence == "high"
                for reference in self.source_refs
            ):
                raise ValueError("confirmed API case requires a high-confidence OpenAPI source")
        elif self.request.method is not None or self.request.path is not None:
            raise ValueError("unconfirmed API case must keep request.method and request.path null")
        return self


class ConfirmedApiTestCase(ApiTestCase):
    contract_status: Literal["confirmed"]
    request: ConfirmedApiRequest


class UnconfirmedApiTestCase(ApiTestCase):
    contract_status: Literal["missing", "pending_confirmation", "partial"]
    request: UnconfirmedApiRequest


TypedApiTestCase = Annotated[
    ConfirmedApiTestCase | UnconfirmedApiTestCase,
    Field(discriminator="contract_status"),
]


class ApiTestCasesDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["agentic-qa.api-cases.v1.1"]
    artifact_type: Literal["api_automation_cases"]
    status: Literal["needs_human_review"]
    human_review_required: Literal[True]
    base_url_env: Literal["AGENTIC_QA_BASE_URL"]
    business_rules: list[Any] = Field(min_length=1)
    source_refs: list[SourceRef] = Field(min_length=1)
    cases: list[TypedApiTestCase] = Field(min_length=1)
    review_questions: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_case_ids(self) -> ApiTestCasesDraft:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("API case ids must be unique")
        return self
