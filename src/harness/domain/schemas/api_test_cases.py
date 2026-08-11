from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from harness.domain.security import (
    SECRET_KEY,
    validate_api_assertion_expected_safety,
    validate_api_data_safety,
    validate_api_request_safety,
)

API_CASES_SCHEMA_VERSION = "agentic-qa.api-cases.v1.1"
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}
SUPPORTED_API_ASSERTION_TYPES = frozenset(
    {
        "status_code",
        "json_field_exists",
        "json_field_equals",
        "json_field_contains",
        "header_equals",
        "response_time_ms_max",
    }
)
JSON_PATH_TOKEN = re.compile(
    r"(?:\.(?P<field>[A-Za-z_][A-Za-z0-9_-]*)|\[(?P<index>0|[1-9][0-9]*)\])"
)
VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
VARIABLE_PLACEHOLDER = re.compile(r"\$\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
HTTP_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
SENSITIVE_RESPONSE_HEADER = re.compile(
    r"(authorization|cookie|token|secret|password|api[_-]?key)",
    re.IGNORECASE,
)


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


class ApiDataset(StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    values: dict[str, Any] = Field(min_length=1, max_length=100)

    @field_validator("values")
    @classmethod
    def validate_variable_names(cls, value: dict[str, Any]) -> dict[str, Any]:
        invalid = sorted(name for name in value if not VARIABLE_NAME.fullmatch(name))
        if invalid:
            raise ValueError(f"invalid dataset variable names: {invalid}")
        return value


class ApiVariableExtraction(StrictModel):
    source: Literal["response_json", "response_header"]
    path: str = Field(min_length=1)
    required: bool = True

    @model_validator(mode="after")
    def validate_source_path(self) -> ApiVariableExtraction:
        if self.source == "response_json":
            json_path_tokens(self.path)
        elif not HTTP_HEADER_NAME.fullmatch(self.path) or SENSITIVE_RESPONSE_HEADER.search(
            self.path
        ):
            raise ValueError(
                "response_header extraction requires a valid non-sensitive response header name"
            )
        return self


class ApiCaseVariables(StrictModel):
    datasets: list[ApiDataset] = Field(default_factory=list, max_length=100)
    extract: dict[str, ApiVariableExtraction] = Field(default_factory=dict, max_length=100)

    @field_validator("datasets")
    @classmethod
    def validate_dataset_ids_and_shapes(cls, value: list[ApiDataset]) -> list[ApiDataset]:
        ids = [dataset.id for dataset in value]
        if len(ids) != len(set(ids)):
            raise ValueError("dataset ids must be unique")
        if value:
            expected_names = set(value[0].values)
            if any(set(dataset.values) != expected_names for dataset in value[1:]):
                raise ValueError("all datasets in one API case must define the same variables")
        return value

    @field_validator("extract")
    @classmethod
    def validate_extraction_names(
        cls, value: dict[str, ApiVariableExtraction]
    ) -> dict[str, ApiVariableExtraction]:
        invalid = sorted(name for name in value if not VARIABLE_NAME.fullmatch(name))
        if invalid:
            raise ValueError(f"invalid extracted variable names: {invalid}")
        return value

    @model_validator(mode="after")
    def validate_no_local_name_collision(self) -> ApiCaseVariables:
        dataset_names = set(self.datasets[0].values) if self.datasets else set()
        collisions = sorted(dataset_names & set(self.extract))
        if collisions:
            raise ValueError(f"dataset and extraction variable names collide: {collisions}")
        return self


class ApiCleanupStep(StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    title: str = Field(default="cleanup", min_length=1, max_length=200)
    request: ConfirmedApiRequest
    assertions: list[ApiAssertion] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_assertions(self) -> ApiCleanupStep:
        validate_api_assertion_definitions(self.assertions)
        return self


def json_path_tokens(path: str) -> tuple[str | int, ...]:
    if path == "$":
        return ()
    if not path.startswith("$"):
        raise ValueError("JSON assertion path must start with '$'")
    tokens: list[str | int] = []
    cursor = 1
    while cursor < len(path):
        match = JSON_PATH_TOKEN.match(path, cursor)
        if match is None:
            raise ValueError(
                "JSON assertion path only supports '.field' and non-negative '[index]' tokens"
            )
        field = match.group("field")
        tokens.append(field if field is not None else int(match.group("index")))
        cursor = match.end()
    if cursor != len(path):
        raise ValueError("JSON assertion path is invalid")
    return tuple(tokens)


def validate_api_assertion_definition(assertion: ApiAssertion) -> None:
    assertion_type = assertion.type
    if assertion_type not in SUPPORTED_API_ASSERTION_TYPES:
        raise ValueError(f"unsupported API assertion type: {assertion_type}")

    expected_is_set = "expected" in assertion.model_fields_set
    path = assertion.path
    if assertion_type == "status_code":
        if path is not None:
            raise ValueError("status_code assertion does not accept path")
        if not expected_is_set:
            raise ValueError("status_code assertion requires expected")
        values = (
            assertion.expected if isinstance(assertion.expected, list) else [assertion.expected]
        )
        if (
            not values
            or any(not isinstance(value, int) or isinstance(value, bool) for value in values)
            or any(value < 100 or value > 599 for value in values)
            or len(values) != len(set(values))
        ):
            raise ValueError(
                "status_code expected must be a unique HTTP status code or non-empty list"
            )
        return

    if assertion_type in {
        "json_field_exists",
        "json_field_equals",
        "json_field_contains",
    }:
        if path is None:
            raise ValueError(f"{assertion_type} assertion requires path")
        json_path_tokens(path)
        if assertion_type == "json_field_exists":
            if (
                expected_is_set
                and assertion.expected is not None
                and assertion.expected is not True
            ):
                raise ValueError("json_field_exists expected may only be omitted or true")
        elif not expected_is_set:
            raise ValueError(f"{assertion_type} assertion requires expected")
        else:
            if any(
                isinstance(token, str) and SECRET_KEY.search(token)
                for token in json_path_tokens(path)
            ):
                raise ValueError(f"{assertion_type} cannot target a sensitive JSON field")
            validate_api_assertion_expected_safety(
                assertion.expected,
                label=f"{assertion_type} assertion",
            )
        return

    if assertion_type == "header_equals":
        if (
            path is None
            or not HTTP_HEADER_NAME.fullmatch(path)
            or SENSITIVE_RESPONSE_HEADER.search(path)
        ):
            raise ValueError("header_equals requires a valid non-sensitive response header name")
        if (
            not expected_is_set
            or not isinstance(assertion.expected, str)
            or "\r" in assertion.expected
            or "\n" in assertion.expected
        ):
            raise ValueError("header_equals expected must be a string without line breaks")
        validate_api_assertion_expected_safety(
            assertion.expected,
            label="header_equals assertion",
        )
        return

    if path is not None:
        raise ValueError("response_time_ms_max assertion does not accept path")
    if (
        not expected_is_set
        or not isinstance(assertion.expected, int)
        or isinstance(assertion.expected, bool)
        or assertion.expected < 1
        or assertion.expected > 60_000
    ):
        raise ValueError("response_time_ms_max expected must be an integer from 1 to 60000")


def validate_api_assertion_definitions(assertions: list[ApiAssertion]) -> None:
    for index, assertion in enumerate(assertions):
        try:
            validate_api_assertion_definition(assertion)
        except ValueError as exc:
            raise ValueError(f"assertions[{index}]: {exc}") from exc


def parse_api_case_variables(value: dict[str, Any]) -> ApiCaseVariables:
    return ApiCaseVariables.model_validate(value)


def parse_api_cleanup_steps(value: list[Any]) -> list[ApiCleanupStep]:
    steps = [ApiCleanupStep.model_validate(item) for item in value]
    ids = [step.id for step in steps]
    if len(ids) != len(set(ids)):
        raise ValueError("cleanup step ids must be unique within an API case")
    return steps


def api_execution_case_ids(cases: list[ApiTestCase]) -> list[str]:
    main_ids: list[str] = []
    cleanup_ids: list[str] = []
    for case in cases:
        variables = parse_api_case_variables(case.variables)
        cleanup = parse_api_cleanup_steps(case.cleanup)
        instance_ids = (
            [f"{case.id}::{dataset.id}" for dataset in variables.datasets]
            if variables.datasets
            else [case.id]
        )
        main_ids.extend(instance_ids)
        for instance_id in instance_ids:
            cleanup_ids.extend(f"{instance_id}::cleanup::{step.id}" for step in cleanup)
    return [*main_ids, *reversed(cleanup_ids)]


def variable_references(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(VARIABLE_PLACEHOLDER.findall(value))
    if isinstance(value, list):
        return set().union(*(variable_references(item) for item in value), set())
    if isinstance(value, dict):
        return set().union(*(variable_references(item) for item in value.values()), set())
    return set()


def _reject_malformed_variable_placeholders(value: Any) -> None:
    if isinstance(value, str):
        remainder = VARIABLE_PLACEHOLDER.sub("", value)
        if "${{" in remainder or "}}" in remainder:
            raise ValueError("malformed runtime variable placeholder")
    elif isinstance(value, list):
        for item in value:
            _reject_malformed_variable_placeholders(item)
    elif isinstance(value, dict):
        for item in value.values():
            _reject_malformed_variable_placeholders(item)


def api_case_runtime_definition_errors(cases: list[ApiTestCase]) -> list[str | None]:
    """Validate scenario semantics while preserving per-case execution blocking."""
    errors: list[str | None] = []
    available: set[str] = set()
    seen_case_ids: set[str] = set()
    for case in cases:
        try:
            if case.id in seen_case_ids:
                raise ValueError(f"duplicate API case id: {case.id}")
            seen_case_ids.add(case.id)
            if "::" in case.id:
                raise ValueError("API case ids cannot contain the reserved '::' separator")
            validate_api_assertion_definitions(case.assertions)
            variables = parse_api_case_variables(case.variables)
            cleanup = parse_api_cleanup_steps(case.cleanup)
            request_payload = case.request.model_dump(mode="python")
            _reject_malformed_variable_placeholders(request_payload)
            dataset_names = set(variables.datasets[0].values) if variables.datasets else set()
            collisions = sorted(dataset_names & available)
            if collisions:
                raise ValueError(f"dataset variables shadow earlier extracted values: {collisions}")
            collisions = sorted(set(variables.extract) & available)
            if collisions:
                raise ValueError(f"extracted variable names are already defined: {collisions}")
            for dataset in variables.datasets:
                validate_api_data_safety(
                    dataset.values,
                    label=f"API dataset {dataset.id}",
                    allow_runtime_variables=False,
                )
            validate_api_request_safety(
                path=case.request.path,
                headers=case.request.headers,
                query=case.request.query,
                body=case.request.body,
                label="API request",
                allow_runtime_variables=True,
            )
            missing = variable_references(request_payload) - available - dataset_names
            if missing:
                raise ValueError(
                    f"request references variables not produced by an earlier case or dataset: "
                    f"{sorted(missing)}"
                )
            cleanup_available = available | dataset_names | set(variables.extract)
            for index, step in enumerate(cleanup):
                payload = step.request.model_dump(mode="python")
                _reject_malformed_variable_placeholders(payload)
                validate_api_request_safety(
                    path=step.request.path,
                    headers=step.request.headers,
                    query=step.request.query,
                    body=step.request.body,
                    label=f"API cleanup {step.id}",
                    allow_runtime_variables=True,
                )
                missing = variable_references(payload) - cleanup_available
                if missing:
                    raise ValueError(
                        f"cleanup[{index}] references unavailable variables: {sorted(missing)}"
                    )
            if case.contract_status != "confirmed" and (variables.extract or cleanup):
                raise ValueError("unconfirmed API cases cannot extract variables or run cleanup")
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))
        else:
            errors.append(None)
            available.update(variables.extract)
    return errors


def validate_api_case_runtime_definitions(cases: list[ApiTestCase]) -> None:
    for index, error in enumerate(api_case_runtime_definition_errors(cases)):
        if error is not None:
            raise ValueError(f"cases[{index}]: {error}")
    ids = api_execution_case_ids(cases)
    if len(ids) != len(set(ids)):
        raise ValueError("expanded API execution evidence ids must be unique")


def validate_api_cleanup_policy(
    cases: list[ApiTestCase],
    cleanup_exempt_operations: list[str] | tuple[str, ...],
    operation_policies: dict[str, Any] | None = None,
) -> None:
    exemptions = set(cleanup_exempt_operations)
    policies = operation_policies or {}
    for case in cases:
        if case.contract_status != "confirmed":
            continue
        operation = f"{case.request.method} {case.request.path}"
        configured = policies.get(operation)
        classification = (
            configured.get("classification")
            if isinstance(configured, dict)
            else getattr(configured, "classification", None)
        )
        if classification is None:
            classification = (
                "mutation_cleanup"
                if case.request.method in {"POST", "PUT", "PATCH", "DELETE"}
                else "read_only"
            )
        if operation in exemptions:
            classification = "read_only"
        if classification == "mutation_manual":
            raise ValueError(
                f"{case.id} operation is manual-only and cannot be published as executable: "
                f"{operation}"
            )
        if classification != "read_only" and not parse_api_cleanup_steps(case.cleanup):
            raise ValueError(
                f"{case.id} mutating operation requires cleanup or an exact policy exemption: "
                f"{operation}"
            )


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
