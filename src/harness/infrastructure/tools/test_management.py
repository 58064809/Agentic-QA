from __future__ import annotations

import json
import os
from enum import Enum
from typing import Any, Literal
from urllib.parse import urlsplit

import requests
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TestManagementOperation(str, Enum):
    LIST_PROJECTS = "list_projects"
    LIST_SUITES = "list_suites"
    LIST_SECTIONS = "list_sections"
    LIST_CASES = "list_cases"
    GET_CASE = "get_case"


class TestRailSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(
        default="agentic-qa.harness.testrail-source.v1",
        pattern=r"^agentic-qa\.harness\.testrail-source\.v1$",
    )
    base_url_env: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    username_env: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    api_key_env: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    timeout_seconds: int = Field(default=10, ge=1, le=30)
    max_items: int = Field(default=250, ge=1, le=250)
    max_response_bytes: int = Field(default=1_048_576, ge=1024, le=2_097_152)

    @model_validator(mode="after")
    def validate_distinct_environment_names(self) -> TestRailSourceConfig:
        names = (self.base_url_env, self.username_env, self.api_key_env)
        if len(set(names)) != len(names):
            raise ValueError("TestRail environment variable names must be distinct")
        return self

    def credentials(self, env: dict[str, str] | None = None) -> tuple[str, str, str]:
        values = env if env is not None else os.environ
        missing = [
            name
            for name in (self.base_url_env, self.username_env, self.api_key_env)
            if not values.get(name)
        ]
        if missing:
            raise RuntimeError(
                "TestRail configuration is missing environment values: " + ", ".join(missing)
            )
        base_url = _validated_base_url(values[self.base_url_env])
        return base_url, values[self.username_env], values[self.api_key_env]


class TestManagementQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: TestManagementOperation
    project_id: int | None = Field(default=None, ge=1)
    suite_id: int | None = Field(default=None, ge=1)
    section_id: int | None = Field(default=None, ge=1)
    case_id: int | None = Field(default=None, ge=1)
    limit: int = Field(default=100, ge=1, le=250)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_operation_arguments(self) -> TestManagementQuery:
        required: dict[TestManagementOperation, tuple[str, ...]] = {
            TestManagementOperation.LIST_PROJECTS: (),
            TestManagementOperation.LIST_SUITES: ("project_id",),
            TestManagementOperation.LIST_SECTIONS: ("project_id",),
            TestManagementOperation.LIST_CASES: ("project_id",),
            TestManagementOperation.GET_CASE: ("case_id",),
        }
        missing = [name for name in required[self.operation] if getattr(self, name) is None]
        if missing:
            raise ValueError(
                f"{self.operation.value} requires arguments: {', '.join(sorted(missing))}"
            )
        allowed: dict[TestManagementOperation, set[str]] = {
            TestManagementOperation.LIST_PROJECTS: set(),
            TestManagementOperation.LIST_SUITES: {"project_id"},
            TestManagementOperation.LIST_SECTIONS: {"project_id", "suite_id"},
            TestManagementOperation.LIST_CASES: {"project_id", "suite_id", "section_id"},
            TestManagementOperation.GET_CASE: {"case_id"},
        }
        supplied = {
            name
            for name in ("project_id", "suite_id", "section_id", "case_id")
            if getattr(self, name) is not None
        }
        unexpected = sorted(supplied - allowed[self.operation])
        if unexpected:
            raise ValueError(
                f"{self.operation.value} does not accept arguments: {', '.join(unexpected)}"
            )
        return self


class TestManagementSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    origin: str
    resource: str


class TestManagementPagination(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=250)
    returned: int = Field(ge=0, le=250)
    next_offset: int | None = Field(default=None, ge=0)
    truncated: bool


class TestManagementResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agentic-qa.harness.test-management-result.v1"] = (
        "agentic-qa.harness.test-management-result.v1"
    )
    provider: Literal["testrail"] = "testrail"
    operation: TestManagementOperation
    source: TestManagementSource
    records: list[dict[str, Any]] = Field(max_length=250)
    pagination: TestManagementPagination


def read_testrail(
    config: TestRailSourceConfig,
    query: TestManagementQuery,
    *,
    env: dict[str, str] | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    base_url, username, api_key = config.credentials(env)
    endpoint, parameters, collection_key = _request_spec(query)
    limit = min(query.limit, config.max_items)
    if query.operation != TestManagementOperation.GET_CASE:
        parameters.update({"limit": limit, "offset": query.offset})
    url = f"{base_url}/index.php?/api/v2/{endpoint}"
    owns_session = session is None
    client = session or requests.Session()
    try:
        response = client.get(
            url,
            params=parameters,
            headers={"Accept": "application/json"},
            auth=(username, api_key),
            timeout=config.timeout_seconds,
            allow_redirects=False,
            stream=True,
        )
        if 300 <= response.status_code < 400:
            raise RuntimeError("TestRail redirect was rejected to protect credentials")
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"TestRail returned HTTP {response.status_code}")
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise RuntimeError("TestRail returned an invalid Content-Length") from exc
            if declared_size > config.max_response_bytes:
                raise RuntimeError("TestRail response exceeds max_response_bytes")
        raw = _bounded_response_body(response, config.max_response_bytes)
    finally:
        if owns_session:
            client.close()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("TestRail returned invalid UTF-8 JSON") from exc
    records, pagination = _normalize_response(payload, collection_key, query, limit)
    return TestManagementResult(
        operation=query.operation,
        source=TestManagementSource(
            origin=_origin(base_url),
            resource=endpoint,
        ),
        records=records,
        pagination=TestManagementPagination.model_validate(pagination),
    ).model_dump(mode="json")


def _validated_base_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("TestRail base URL must be an HTTPS URL without credentials or query")
    return candidate


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def _request_spec(
    query: TestManagementQuery,
) -> tuple[str, dict[str, int], str | None]:
    if query.operation == TestManagementOperation.LIST_PROJECTS:
        return "get_projects", {}, "projects"
    if query.operation == TestManagementOperation.LIST_SUITES:
        return f"get_suites/{query.project_id}", {}, "suites"
    if query.operation == TestManagementOperation.LIST_SECTIONS:
        parameters = {"suite_id": query.suite_id} if query.suite_id is not None else {}
        return f"get_sections/{query.project_id}", parameters, "sections"
    if query.operation == TestManagementOperation.LIST_CASES:
        parameters = {}
        if query.suite_id is not None:
            parameters["suite_id"] = query.suite_id
        if query.section_id is not None:
            parameters["section_id"] = query.section_id
        return f"get_cases/{query.project_id}", parameters, "cases"
    return f"get_case/{query.case_id}", {}, None


def _bounded_response_body(response: requests.Response, maximum: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(chunk_size=65_536):
        if not chunk:
            continue
        size += len(chunk)
        if size > maximum:
            raise RuntimeError("TestRail response exceeds max_response_bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _normalize_response(
    payload: Any,
    collection_key: str | None,
    query: TestManagementQuery,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, int | bool | None]]:
    if collection_key is None:
        if not isinstance(payload, dict):
            raise RuntimeError("TestRail case response must be an object")
        records = [payload]
        size = 1
        next_offset = None
    elif isinstance(payload, list):
        records = payload
        size = len(records)
        next_offset = query.offset + size if size == limit else None
    elif isinstance(payload, dict) and isinstance(payload.get(collection_key), list):
        records = payload[collection_key]
        size = int(payload.get("size", len(records)))
        links = payload.get("_links")
        next_offset = (
            query.offset + len(records) if isinstance(links, dict) and links.get("next") else None
        )
    else:
        raise RuntimeError(f"TestRail response is missing the {collection_key!r} collection")
    if len(records) > limit:
        records = records[:limit]
    if any(not isinstance(item, dict) for item in records):
        raise RuntimeError("TestRail records must be objects")
    return records, {
        "offset": query.offset,
        "limit": limit,
        "returned": len(records),
        "next_offset": next_offset,
        "truncated": next_offset is not None,
    }
