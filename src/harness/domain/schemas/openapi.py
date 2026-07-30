from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class OpenApiParameter(StrictModel):
    name: str = Field(min_length=1)
    location: Literal["query", "header", "path", "cookie", "body", "formData"]
    required: bool = False
    description: str = ""
    schema_value: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="schema",
        serialization_alias="schema",
    )


class OpenApiRequestBody(StrictModel):
    required: bool = False
    description: str = ""
    content: dict[str, dict[str, Any]] = Field(default_factory=dict)


class OpenApiResponse(StrictModel):
    status: str = Field(min_length=1)
    description: str = ""
    content: dict[str, dict[str, Any]] = Field(default_factory=dict)


class OpenApiEndpoint(StrictModel):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"]
    path: str = Field(min_length=1)
    operation_id: str = ""
    summary: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    deprecated: bool = False
    parameters: list[OpenApiParameter] = Field(default_factory=list)
    request_body: OpenApiRequestBody | None = None
    responses: list[OpenApiResponse] = Field(default_factory=list)
    security: list[dict[str, list[str]]] = Field(default_factory=list)


class OpenApiInspection(StrictModel):
    schema_version: Literal["agentic-qa.openapi-inspection.v1"] = "agentic-qa.openapi-inspection.v1"
    source: str = Field(min_length=1)
    contract_status: Literal["confirmed"] = "confirmed"
    specification: Literal["openapi", "swagger"]
    specification_version: str = Field(min_length=1)
    title: str = ""
    server_urls: list[str] = Field(default_factory=list)
    security_schemes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    endpoint_count: int = Field(ge=1)
    endpoints: list[OpenApiEndpoint] = Field(min_length=1, max_length=500)
