from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NetworkCall(StrictModel):
    sequence: int = Field(ge=1)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"]
    origin: str | None = None
    path: str = Field(min_length=1)
    status: int | None = Field(default=None, ge=100, le=599)
    resource_type: str = ""
    page_path: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    business_candidate: bool


class DiscoveredApiCandidate(StrictModel):
    candidate_id: str = Field(pattern=r"^DISC-\d{3}$")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"]
    origin: str | None = None
    path: str = Field(min_length=1)
    call_count: int = Field(ge=1)
    status_codes: list[int]
    average_duration_ms: float | None = Field(default=None, ge=0)
    query_parameters: list[str]
    request_schema: dict[str, Any]
    response_schema: dict[str, Any]
    source_path: str = Field(min_length=1)
    locators: list[str] = Field(min_length=1)
    evidence_kind: Literal["playwright-network-capture"] = "playwright-network-capture"
    confidence: Literal["observed"] = "observed"
    pending: list[str] = Field(min_length=1)


class ApiDiscoveryCatalog(StrictModel):
    schema_version: Literal["agentic-qa.api-discovery.v1.1"] = "agentic-qa.api-discovery.v1.1"
    source_path: str = Field(min_length=1)
    capture_format: Literal["har", "simplified_json", "playwright_mcp"]
    observed_call_count: int = Field(ge=0)
    business_candidate_count: int = Field(ge=0)
    calls: list[NetworkCall] = Field(max_length=500)
    candidates: list[DiscoveredApiCandidate] = Field(max_length=500)
    redactions: list[str]
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_counts(self) -> ApiDiscoveryCatalog:
        if self.observed_call_count != len(self.calls):
            raise ValueError("observed_call_count does not match calls")
        if self.business_candidate_count != len(self.candidates):
            raise ValueError("business_candidate_count does not match candidates")
        return self


class ApiDiscoveryExport(StrictModel):
    schema_version: Literal["agentic-qa.api-discovery-export.v1"] = (
        "agentic-qa.api-discovery-export.v1"
    )
    run_id: str = Field(min_length=1)
    catalogs: list[ApiDiscoveryCatalog] = Field(min_length=1, max_length=50)
