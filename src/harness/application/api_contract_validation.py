from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict

from harness.domain.schemas.api_test_cases import (
    ApiAssertion,
    ApiRequest,
    ApiTestCase,
    ApiTestCasesDraft,
    ApiVariableExtraction,
    json_path_tokens,
    parse_api_case_variables,
    parse_api_cleanup_steps,
)
from harness.domain.schemas.openapi import (
    OpenApiEndpoint,
    OpenApiInspection,
    OpenApiParameter,
    OpenApiResponse,
)

RUNTIME_REFERENCE = re.compile(r"\$\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
FULL_RUNTIME_REFERENCE = re.compile(r"^\$\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}$")
PATH_PARAMETER_SEGMENT = re.compile(r"^\{([^{}\/]+)\}$")
JSON_MEDIA_TYPE = re.compile(r"^(?:application/json|[^;/\s]+/[^;/\s]+\+json)(?:\s*;.*)?$", re.I)


class ApiContractIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    case_id: str
    instance_id: str
    location: str
    message: str


class ApiContractValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check_count: int
    issues: tuple[ApiContractIssue, ...] = ()

    @property
    def semantic_rate(self) -> float:
        if self.check_count <= 0:
            return 0.0
        return max(self.check_count - len(self.issues), 0) / self.check_count


@dataclass(frozen=True)
class _Unresolved:
    name: str
    guaranteed_type: str | None = None


class _ExpansionError(ValueError):
    pass


@dataclass(frozen=True)
class _MatchedEndpoint:
    inspection: OpenApiInspection
    endpoint: OpenApiEndpoint
    path_values: Mapping[str, str]


def validate_api_contracts(
    draft: ApiTestCasesDraft,
    inspections: Iterable[OpenApiInspection],
) -> ApiContractValidationResult:
    available_inspections = tuple(inspections)
    issues: list[ApiContractIssue] = []
    checks = 0
    for case in draft.cases:
        if case.contract_status != "confirmed":
            continue
        variables = parse_api_case_variables(case.variables)
        datasets = variables.datasets or [None]
        for dataset in datasets:
            instance_id = f"{case.id}::{dataset.id}" if dataset is not None else case.id
            values = dataset.values if dataset is not None else {}
            result_checks, result_issues = _validate_request_contract(
                case=case,
                instance_id=instance_id,
                request=case.request,
                assertions=case.assertions,
                extractions=variables.extract,
                variables=values,
                inspections=available_inspections,
                location="request",
            )
            checks += result_checks
            issues.extend(result_issues)
            for cleanup in parse_api_cleanup_steps(case.cleanup):
                result_checks, result_issues = _validate_request_contract(
                    case=case,
                    instance_id=f"{instance_id}::cleanup::{cleanup.id}",
                    request=cleanup.request,
                    assertions=cleanup.assertions,
                    extractions={},
                    variables=values,
                    inspections=available_inspections,
                    location=f"cleanup.{cleanup.id}",
                )
                checks += result_checks
                issues.extend(result_issues)
    return ApiContractValidationResult(check_count=checks, issues=tuple(issues))


def _validate_request_contract(
    *,
    case: ApiTestCase,
    instance_id: str,
    request: ApiRequest,
    assertions: list[ApiAssertion],
    extractions: Mapping[str, ApiVariableExtraction],
    variables: Mapping[str, Any],
    inspections: tuple[OpenApiInspection, ...],
    location: str,
) -> tuple[int, list[ApiContractIssue]]:
    checks = 1
    issues: list[ApiContractIssue] = []
    referenced_sources = {
        reference.source_path
        for reference in case.source_refs
        if reference.source_type == "openapi" and reference.confidence == "high"
    }
    scoped = tuple(item for item in inspections if item.source in referenced_sources)
    matches = _matching_endpoints(request, scoped)
    if not matches:
        return checks, [
            _issue(
                "operation_not_found",
                case,
                instance_id,
                location,
                f"{request.method} {request.path} does not match a referenced OpenAPI operation",
            )
        ]
    if len(matches) > 1:
        return checks, [
            _issue(
                "ambiguous_operation",
                case,
                instance_id,
                location,
                f"{request.method} {request.path} matches multiple OpenAPI operations",
            )
        ]
    match = matches[0]
    endpoint = match.endpoint
    parameters = {(item.location, item.name.casefold()): item for item in endpoint.parameters}

    supplied_by_location: dict[str, Mapping[str, Any]] = {
        "query": request.query if isinstance(request.query, dict) else {},
        "header": request.headers,
    }
    if not isinstance(request.query, dict):
        checks += 1
        issues.append(
            _issue(
                "invalid_query_shape",
                case,
                instance_id,
                f"{location}.query",
                "query parameters must be an object",
            )
        )
    for parameter_location, supplied in supplied_by_location.items():
        declared = {
            name: parameter
            for (declared_location, name), parameter in parameters.items()
            if declared_location == parameter_location
        }
        supplied_names = {str(name).casefold() for name in supplied}
        for name, raw_value in supplied.items():
            checks += 1
            folded = str(name).casefold()
            if parameter_location == "header" and folded in {"accept", "content-type"}:
                continue
            parameter = declared.get(folded)
            if parameter is None:
                issues.append(
                    _issue(
                        "undeclared_parameter",
                        case,
                        instance_id,
                        f"{location}.{parameter_location}.{name}",
                        f"{parameter_location} parameter {name} is not declared by OpenAPI",
                    )
                )
                continue
            try:
                value = _expand_value(raw_value, variables)
            except _ExpansionError as exc:
                issues.append(
                    _issue(
                        "non_scalar_interpolation",
                        case,
                        instance_id,
                        f"{location}.{parameter_location}.{name}",
                        str(exc),
                    )
                )
                continue
            value = _coerce_scalar_by_schema(value, parameter.schema_value)
            issues.extend(
                _schema_issues(
                    value,
                    parameter.schema_value,
                    specification=match.inspection.specification,
                    case=case,
                    instance_id=instance_id,
                    location=f"{location}.{parameter_location}.{name}",
                )
            )
        for name, parameter in declared.items():
            if parameter.required:
                checks += 1
                if name not in supplied_names:
                    issues.append(
                        _issue(
                            "missing_required_parameter",
                            case,
                            instance_id,
                            f"{location}.{parameter_location}.{parameter.name}",
                            f"required {parameter_location} parameter {parameter.name} is missing",
                        )
                    )

    path_parameters = {item.name: item for item in endpoint.parameters if item.location == "path"}
    template_names = set(match.path_values)
    for name, raw_value in match.path_values.items():
        checks += 1
        parameter = path_parameters.get(name)
        if parameter is None:
            issues.append(
                _issue(
                    "undeclared_path_parameter",
                    case,
                    instance_id,
                    f"{location}.path.{name}",
                    f"OpenAPI path template parameter {name} has no parameter definition",
                )
            )
            continue
        reference = FULL_RUNTIME_REFERENCE.fullmatch(raw_value)
        if reference is None:
            issues.append(
                _issue(
                    "path_parameter_requires_variable",
                    case,
                    instance_id,
                    f"{location}.path.{name}",
                    f"path parameter {name} must use a complete runtime variable placeholder",
                )
            )
            continue
        value = _path_parameter_value(raw_value, variables, parameter)
        if value is None or isinstance(value, dict | list):
            issues.append(
                _issue(
                    "non_scalar_path_parameter",
                    case,
                    instance_id,
                    f"{location}.path.{name}",
                    f"path parameter {name} must resolve to a scalar value",
                )
            )
            continue
        issues.extend(
            _schema_issues(
                value,
                parameter.schema_value,
                specification=match.inspection.specification,
                case=case,
                instance_id=instance_id,
                location=f"{location}.path.{name}",
            )
        )
    for name, parameter in path_parameters.items():
        checks += 1
        if not parameter.required:
            issues.append(
                _issue(
                    "optional_path_parameter",
                    case,
                    instance_id,
                    f"{location}.path.{name}",
                    f"OpenAPI path parameter {name} must be required",
                )
            )
        if name not in template_names:
            issues.append(
                _issue(
                    "unused_path_parameter",
                    case,
                    instance_id,
                    f"{location}.path.{name}",
                    f"declared path parameter {name} is absent from the OpenAPI path template",
                )
            )

    checks += 1
    issues.extend(
        _request_body_issues(
            case=case,
            instance_id=instance_id,
            location=location,
            request=request,
            endpoint=endpoint,
            specification=match.inspection.specification,
            variables=variables,
        )
    )
    assertion_checks, assertion_issues = _response_contract_issues(
        case=case,
        instance_id=instance_id,
        location=location,
        endpoint=endpoint,
        assertions=assertions,
        extractions=extractions,
        specification=match.inspection.specification,
    )
    return checks + assertion_checks, [*issues, *assertion_issues]


def _matching_endpoints(
    request: ApiRequest,
    inspections: tuple[OpenApiInspection, ...],
) -> list[_MatchedEndpoint]:
    matches: list[_MatchedEndpoint] = []
    for inspection in inspections:
        for endpoint in inspection.endpoints:
            if endpoint.method != request.method:
                continue
            path_values = _match_path(endpoint.path, request.path or "")
            if path_values is not None:
                matches.append(
                    _MatchedEndpoint(
                        inspection=inspection,
                        endpoint=endpoint,
                        path_values=path_values,
                    )
                )
    return matches


def _match_path(contract_path: str, request_path: str) -> dict[str, str] | None:
    contract_segments = contract_path.split("/")
    request_segments = request_path.split("/")
    if len(contract_segments) != len(request_segments):
        return None
    values: dict[str, str] = {}
    for contract_segment, request_segment in zip(contract_segments, request_segments, strict=True):
        parameter = PATH_PARAMETER_SEGMENT.fullmatch(contract_segment)
        if parameter is None:
            if "{" in contract_segment or "}" in contract_segment:
                return None
            if contract_segment != request_segment:
                return None
            continue
        if not request_segment or "/" in request_segment:
            return None
        values[parameter.group(1)] = request_segment
    return values


def _path_parameter_value(
    value: str,
    variables: Mapping[str, Any],
    parameter: OpenApiParameter,
) -> Any:
    reference = FULL_RUNTIME_REFERENCE.fullmatch(value)
    if reference is not None:
        return variables.get(reference.group(1), _Unresolved(reference.group(1)))
    return _coerce_scalar_by_schema(value, parameter.schema_value)


def _coerce_scalar_by_schema(value: Any, schema: Mapping[str, Any]) -> Any:
    if not isinstance(value, str):
        return value
    schema_type = schema.get("type")
    try:
        if schema_type == "integer" and re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value):
            return int(value)
        if schema_type == "number":
            return float(value)
        if schema_type == "boolean" and value.casefold() in {"true", "false"}:
            return value.casefold() == "true"
    except ValueError:
        return value
    return value


def _expand_value(value: Any, variables: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        full = FULL_RUNTIME_REFERENCE.fullmatch(value)
        if full is not None:
            return variables.get(full.group(1), _Unresolved(full.group(1)))
        references = RUNTIME_REFERENCE.findall(value)
        if not references:
            return value
        if any(name not in variables for name in references):
            missing = next(name for name in references if name not in variables)
            return _Unresolved(missing, guaranteed_type="string")
        result = value
        for name in references:
            replacement = variables[name]
            if replacement is None or isinstance(replacement, dict | list):
                raise _ExpansionError(
                    f"runtime variable must be scalar when embedded in text: {name}"
                )
            result = result.replace(f"${{{{{name}}}}}", str(replacement))
        return result
    if isinstance(value, list):
        return [_expand_value(item, variables) for item in value]
    if isinstance(value, dict):
        return {str(key): _expand_value(item, variables) for key, item in value.items()}
    return value


def _request_body_issues(
    *,
    case: ApiTestCase,
    instance_id: str,
    location: str,
    request: ApiRequest,
    endpoint: OpenApiEndpoint,
    specification: str,
    variables: Mapping[str, Any],
) -> list[ApiContractIssue]:
    try:
        body = _expand_value(request.body, variables)
    except _ExpansionError as exc:
        return [
            _issue(
                "non_scalar_interpolation",
                case,
                instance_id,
                f"{location}.body",
                str(exc),
            )
        ]
    request_body = endpoint.request_body
    if request_body is None:
        if body not in ({}, None):
            return [
                _issue(
                    "undeclared_request_body",
                    case,
                    instance_id,
                    f"{location}.body",
                    "request body is not declared by OpenAPI",
                )
            ]
        return []
    schemas = [
        schema
        for media_type, schema in request_body.content.items()
        if JSON_MEDIA_TYPE.fullmatch(media_type)
    ]
    if not schemas:
        return [
            _issue(
                "unsupported_request_media_type",
                case,
                instance_id,
                f"{location}.body",
                "API Cases JSON body requires an OpenAPI JSON media type",
            )
        ]
    results = [
        _schema_issues(
            body,
            schema,
            specification=specification,
            case=case,
            instance_id=instance_id,
            location=f"{location}.body",
        )
        for schema in schemas
    ]
    return [] if any(not result for result in results) else min(results, key=len)


def _response_contract_issues(
    *,
    case: ApiTestCase,
    instance_id: str,
    location: str,
    endpoint: OpenApiEndpoint,
    assertions: list[ApiAssertion],
    extractions: Mapping[str, ApiVariableExtraction],
    specification: str,
) -> tuple[int, list[ApiContractIssue]]:
    checks = 0
    issues: list[ApiContractIssue] = []
    responses = {item.status: item for item in endpoint.responses}
    selected: list[OpenApiResponse] = []
    for assertion in assertions:
        if assertion.type != "status_code":
            continue
        values = (
            assertion.expected if isinstance(assertion.expected, list) else [assertion.expected]
        )
        for value in values:
            checks += 1
            code = str(value)
            response = _response_for_code(responses, code)
            if response is None:
                issues.append(
                    _issue(
                        "undeclared_response_status",
                        case,
                        instance_id,
                        f"{location}.assertions.status_code",
                        f"response status {code} is not declared by OpenAPI",
                    )
                )
            elif response not in selected:
                selected.append(response)
    if not selected:
        selected = list(endpoint.responses)
    response_schemas = [
        schema
        for response in selected
        for media_type, schema in response.content.items()
        if JSON_MEDIA_TYPE.fullmatch(media_type)
    ]
    response_headers = {
        name.casefold(): schema
        for response in selected
        for name, schema in response.headers.items()
    }
    for assertion in assertions:
        if assertion.type.startswith("json_field_"):
            checks += 1
            targets = [
                target
                for schema in response_schemas
                for target in _schemas_at_json_path(schema, assertion.path or "$")
            ]
            if not targets:
                issues.append(
                    _issue(
                        "undeclared_response_json_path",
                        case,
                        instance_id,
                        f"{location}.assertions.{assertion.path}",
                        f"response JSON path {assertion.path} is not declared by OpenAPI",
                    )
                )
            elif assertion.type == "json_field_equals" and not any(
                not _raw_schema_errors(assertion.expected, target, specification)
                for target in targets
            ):
                issues.append(
                    _issue(
                        "assertion_expected_schema_mismatch",
                        case,
                        instance_id,
                        f"{location}.assertions.{assertion.path}",
                        f"expected value for {assertion.path} does not satisfy response Schema",
                    )
                )
        elif assertion.type == "header_equals":
            checks += 1
            schema = response_headers.get((assertion.path or "").casefold())
            if schema is None:
                issues.append(
                    _issue(
                        "undeclared_response_header",
                        case,
                        instance_id,
                        f"{location}.assertions.{assertion.path}",
                        f"response header {assertion.path} is not declared by OpenAPI",
                    )
                )
            elif _raw_schema_errors(
                _coerce_scalar_by_schema(assertion.expected, schema),
                schema,
                specification,
            ):
                issues.append(
                    _issue(
                        "assertion_expected_schema_mismatch",
                        case,
                        instance_id,
                        f"{location}.assertions.{assertion.path}",
                        f"expected header {assertion.path} does not satisfy response Schema",
                    )
                )
    for name, extraction in extractions.items():
        checks += 1
        if extraction.source == "response_json":
            valid = any(
                _schemas_at_json_path(schema, extraction.path) for schema in response_schemas
            )
        else:
            valid = extraction.path.casefold() in response_headers
        if not valid:
            issues.append(
                _issue(
                    "undeclared_extraction_source",
                    case,
                    instance_id,
                    f"{location}.extract.{name}",
                    f"extraction source {extraction.path} is not declared by OpenAPI",
                )
            )
    return checks, issues


def _response_for_code(
    responses: Mapping[str, OpenApiResponse], code: str
) -> OpenApiResponse | None:
    if code in responses:
        return responses[code]
    if len(code) == 3 and code.isdigit():
        wildcard = f"{code[0]}XX"
        for status, response in responses.items():
            if status.upper() == wildcard:
                return response
    return responses.get("default")


def _schema_issues(
    value: Any,
    schema: Mapping[str, Any],
    *,
    specification: str,
    case: ApiTestCase,
    instance_id: str,
    location: str,
) -> list[ApiContractIssue]:
    return [
        _issue(
            "schema_mismatch",
            case,
            instance_id,
            location + _json_path_suffix(error.absolute_path),
            error.message,
        )
        for error in _raw_schema_errors(value, schema, specification)
    ]


def _raw_schema_errors(
    value: Any,
    schema: Mapping[str, Any],
    specification: str,
) -> list[Any]:
    normalized = _normalize_openapi_schema(schema, specification)
    try:
        validator = Draft202012Validator(normalized, format_checker=FormatChecker())
        errors = sorted(
            validator.iter_errors(value),
            key=lambda item: tuple(str(token) for token in item.absolute_path),
        )
    except Exception:
        return [] if _contains_unresolved(value) else [_SchemaFailure("invalid OpenAPI Schema")]
    return [error for error in errors if not _deferred_error(error, value)]


@dataclass(frozen=True)
class _SchemaFailure:
    message: str
    absolute_path: tuple[Any, ...] = ()


def _normalize_openapi_schema(value: Any, specification: str) -> Any:
    if isinstance(value, list):
        return [_normalize_openapi_schema(item, specification) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {
        str(key): _normalize_openapi_schema(item, specification)
        for key, item in value.items()
        if key not in {"nullable", "example", "xml", "discriminator"}
    }
    if value.get("nullable") is True:
        schema_type = normalized.get("type")
        if isinstance(schema_type, str):
            normalized["type"] = [schema_type, "null"]
        else:
            normalized = {"anyOf": [normalized, {"type": "null"}]}
    if specification == "swagger":
        normalized.pop("exclusiveMinimum", None)
        normalized.pop("exclusiveMaximum", None)
        if value.get("exclusiveMinimum") is True and isinstance(value.get("minimum"), int | float):
            normalized["exclusiveMinimum"] = value["minimum"]
            normalized.pop("minimum", None)
        if value.get("exclusiveMaximum") is True and isinstance(value.get("maximum"), int | float):
            normalized["exclusiveMaximum"] = value["maximum"]
            normalized.pop("maximum", None)
    return normalized


def _deferred_error(error: Any, instance: Any) -> bool:
    current = instance
    try:
        for token in error.absolute_path:
            current = current[token]
    except (KeyError, IndexError, TypeError):
        return False
    if isinstance(current, _Unresolved):
        if error.validator == "type" and current.guaranteed_type is not None:
            allowed = error.validator_value
            allowed_types = {allowed} if isinstance(allowed, str) else set(allowed)
            return current.guaranteed_type in allowed_types
        return True
    return error.validator in {
        "oneOf",
        "anyOf",
        "allOf",
        "not",
        "if",
        "then",
        "else",
    } and _contains_unresolved(current)


def _contains_unresolved(value: Any) -> bool:
    if isinstance(value, _Unresolved):
        return True
    if isinstance(value, list):
        return any(_contains_unresolved(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_unresolved(item) for item in value.values())
    return False


def _schemas_at_json_path(schema: Mapping[str, Any], path: str) -> list[dict[str, Any]]:
    current = [dict(schema)]
    for token in json_path_tokens(path):
        next_schemas: list[dict[str, Any]] = []
        for candidate in current:
            for expanded in _schema_branches(candidate):
                if isinstance(token, int):
                    items = expanded.get("items")
                    if isinstance(items, dict):
                        next_schemas.append(items)
                else:
                    properties = expanded.get("properties")
                    if isinstance(properties, dict) and isinstance(properties.get(token), dict):
                        next_schemas.append(properties[token])
        current = next_schemas
        if not current:
            break
    return current


def _schema_branches(schema: Mapping[str, Any]) -> list[dict[str, Any]]:
    branches = [dict(schema)]
    for keyword in ("allOf", "anyOf", "oneOf"):
        values = schema.get(keyword)
        if isinstance(values, list):
            branches.extend(item for item in values if isinstance(item, dict))
    return branches


def _json_path_suffix(path: Iterable[Any]) -> str:
    suffix = ""
    for token in path:
        suffix += f"[{token}]" if isinstance(token, int) else f".{token}"
    return suffix


def _issue(
    code: str,
    case: ApiTestCase,
    instance_id: str,
    location: str,
    message: str,
) -> ApiContractIssue:
    return ApiContractIssue(
        code=code,
        case_id=case.id,
        instance_id=instance_id,
        location=location,
        message=message,
    )
