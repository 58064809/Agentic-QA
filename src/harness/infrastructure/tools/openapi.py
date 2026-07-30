from __future__ import annotations

import copy
from typing import Any

from harness.domain.schemas.openapi import (
    OpenApiEndpoint,
    OpenApiInspection,
    OpenApiParameter,
    OpenApiRequestBody,
    OpenApiResponse,
)

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def inspect_openapi(payload: Any, *, source: str) -> OpenApiInspection:
    if not isinstance(payload, dict):
        raise ValueError("source is not a complete OpenAPI/Swagger document")
    specification, version = _specification(payload)
    _validate_references(payload, payload)
    paths = payload.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError("OpenAPI document has no paths")
    info = payload.get("info")
    if (
        not isinstance(info, dict)
        or not str(info.get("title") or "").strip()
        or not str(info.get("version") or "").strip()
    ):
        raise ValueError("OpenAPI document requires info.title and info.version")

    endpoints: list[OpenApiEndpoint] = []
    operation_ids: set[str] = set()
    for path, raw_path_item in sorted(paths.items(), key=lambda item: str(item[0])):
        if not str(path).startswith("/"):
            raise ValueError(f"OpenAPI path must start with '/': {path}")
        path_item = _resolve_object(payload, raw_path_item)
        if not isinstance(path_item, dict):
            continue
        path_parameters = _parameters(payload, path_item.get("parameters"), specification)
        for method, raw_operation in sorted(path_item.items()):
            if method.casefold() not in HTTP_METHODS:
                continue
            operation = _resolve_object(payload, raw_operation)
            if not isinstance(operation, dict):
                continue
            parameters = [
                *path_parameters,
                *_parameters(payload, operation.get("parameters"), specification),
            ]
            parameters = _merge_parameters(parameters)
            responses = _responses(
                payload,
                operation.get("responses"),
                specification=specification,
                produces=_string_list(operation.get("produces") or payload.get("produces")),
            )
            if not responses:
                raise ValueError(f"{method.upper()} {path} has no responses")
            operation_id = str(operation.get("operationId") or "")
            if operation_id and operation_id in operation_ids:
                raise ValueError(f"duplicate OpenAPI operationId: {operation_id}")
            if operation_id:
                operation_ids.add(operation_id)
            request_body = _request_body(
                payload,
                operation,
                parameters,
                specification=specification,
                consumes=_string_list(operation.get("consumes") or payload.get("consumes")),
            )
            if specification == "swagger":
                parameters = [
                    parameter
                    for parameter in parameters
                    if parameter.location not in {"body", "formData"}
                ]
            endpoints.append(
                OpenApiEndpoint(
                    method=method.upper(),
                    path=str(path),
                    operation_id=operation_id,
                    summary=str(operation.get("summary") or ""),
                    description=str(operation.get("description") or ""),
                    tags=_string_list(operation.get("tags")),
                    deprecated=bool(operation.get("deprecated", False)),
                    parameters=parameters,
                    request_body=request_body,
                    responses=responses,
                    security=_security(operation.get("security", payload.get("security"))),
                )
            )
    if not endpoints:
        raise ValueError("OpenAPI document has no HTTP operations")
    if len(endpoints) > 500:
        raise ValueError("OpenAPI document exceeds the 500 endpoint inspection limit")

    components = payload.get("components")
    components = components if isinstance(components, dict) else {}
    security_schemes = (
        components.get("securitySchemes")
        if specification == "openapi"
        else payload.get("securityDefinitions")
    )
    return OpenApiInspection(
        source=source,
        specification=specification,
        specification_version=version,
        title=str(info.get("title") or ""),
        server_urls=_server_urls(payload, specification),
        security_schemes=(
            _resolved_mapping(payload, security_schemes)
            if isinstance(security_schemes, dict)
            else {}
        ),
        endpoint_count=len(endpoints),
        endpoints=endpoints,
    )


def _specification(payload: dict[str, Any]) -> tuple[str, str]:
    openapi = payload.get("openapi")
    swagger = payload.get("swagger")
    if isinstance(openapi, str) and openapi.startswith("3."):
        return "openapi", openapi
    if swagger == "2.0":
        return "swagger", swagger
    raise ValueError("source is not a supported complete OpenAPI 3.x or Swagger 2.0 document")


def _resolve_object(document: dict[str, Any], value: Any) -> Any:
    if not isinstance(value, dict) or not isinstance(value.get("$ref"), str):
        return value
    resolved = _local_ref(document, value["$ref"])
    if not isinstance(resolved, dict):
        return resolved
    return {**resolved, **{key: item for key, item in value.items() if key != "$ref"}}


def _local_ref(document: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise ValueError(f"external OpenAPI reference is unsupported: {reference}")
    current: Any = document
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"unresolved OpenAPI reference: {reference}")
        current = current[part]
    return copy.deepcopy(current)


def _validate_references(document: dict[str, Any], value: Any) -> None:
    if isinstance(value, list):
        for item in value:
            _validate_references(document, item)
        return
    if not isinstance(value, dict):
        return
    reference = value.get("$ref")
    if isinstance(reference, str):
        _local_ref(document, reference)
    for item in value.values():
        _validate_references(document, item)


def _resolved_schema(document: dict[str, Any], value: Any, seen: set[str] | None = None) -> Any:
    if isinstance(value, list):
        return [_resolved_schema(document, item, seen) for item in value]
    if not isinstance(value, dict):
        return value
    reference = value.get("$ref")
    if isinstance(reference, str):
        visited = set(seen or ())
        if reference in visited:
            return {"$ref": reference}
        visited.add(reference)
        resolved = _local_ref(document, reference)
        siblings = {key: item for key, item in value.items() if key != "$ref"}
        if isinstance(resolved, dict):
            resolved = {**resolved, **siblings}
        return _resolved_schema(document, resolved, visited)
    return {str(key): _resolved_schema(document, item, seen) for key, item in value.items()}


def _parameters(document: dict[str, Any], value: Any, specification: str) -> list[OpenApiParameter]:
    if not isinstance(value, list):
        return []
    parameters: list[OpenApiParameter] = []
    for raw_parameter in value:
        parameter = _resolve_object(document, raw_parameter)
        if not isinstance(parameter, dict):
            continue
        location = parameter.get("in")
        if location not in {"query", "header", "path", "cookie", "body", "formData"}:
            continue
        if not str(parameter.get("name") or "").strip():
            raise ValueError(f"OpenAPI {location} parameter requires a name")
        if location == "path" and parameter.get("required") is not True:
            raise ValueError(f"OpenAPI path parameter {parameter['name']} must be required")
        schema = parameter.get("schema")
        if not isinstance(schema, dict):
            schema = {
                key: parameter[key]
                for key in ("type", "format", "items", "enum", "default")
                if key in parameter
            }
        parameters.append(
            OpenApiParameter(
                name=str(parameter.get("name") or location),
                location=location,
                required=bool(parameter.get("required", location == "path")),
                description=str(parameter.get("description") or ""),
                schema=_resolved_schema(document, schema),
            )
        )
    return parameters


def _merge_parameters(parameters: list[OpenApiParameter]) -> list[OpenApiParameter]:
    merged: dict[tuple[str, str], OpenApiParameter] = {}
    for parameter in parameters:
        merged[(parameter.name, parameter.location)] = parameter
    return list(merged.values())


def _request_body(
    document: dict[str, Any],
    operation: dict[str, Any],
    parameters: list[OpenApiParameter],
    *,
    specification: str,
    consumes: list[str],
) -> OpenApiRequestBody | None:
    if specification == "openapi":
        raw_body = _resolve_object(document, operation.get("requestBody"))
        if not isinstance(raw_body, dict):
            return None
        return OpenApiRequestBody(
            required=bool(raw_body.get("required", False)),
            description=str(raw_body.get("description") or ""),
            content=_content(document, raw_body.get("content")),
        )
    body = next((item for item in parameters if item.location == "body"), None)
    form = [item for item in parameters if item.location == "formData"]
    if body is not None:
        media_types = consumes or ["application/json"]
        return OpenApiRequestBody(
            required=body.required,
            description=body.description,
            content={media_type: body.schema_value for media_type in media_types},
        )
    if form:
        media_types = consumes or ["application/x-www-form-urlencoded"]
        schema = {
            "type": "object",
            "properties": {item.name: item.schema_value for item in form},
            "required": [item.name for item in form if item.required],
        }
        return OpenApiRequestBody(
            required=any(item.required for item in form),
            content={media_type: schema for media_type in media_types},
        )
    return None


def _responses(
    document: dict[str, Any],
    value: Any,
    *,
    specification: str,
    produces: list[str],
) -> list[OpenApiResponse]:
    if not isinstance(value, dict):
        return []
    responses: list[OpenApiResponse] = []
    for status, raw_response in sorted(value.items(), key=lambda item: str(item[0])):
        response = _resolve_object(document, raw_response)
        if not isinstance(response, dict):
            continue
        if specification == "openapi":
            content = _content(document, response.get("content"))
        else:
            schema = response.get("schema")
            content = (
                {
                    media_type: _resolved_schema(document, schema)
                    for media_type in (produces or ["application/json"])
                }
                if isinstance(schema, dict)
                else {}
            )
        responses.append(
            OpenApiResponse(
                status=str(status),
                description=str(response.get("description") or ""),
                content=content,
            )
        )
    return responses


def _content(document: dict[str, Any], value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    content: dict[str, dict[str, Any]] = {}
    for media_type, raw_media in sorted(value.items()):
        media = _resolve_object(document, raw_media)
        if not isinstance(media, dict):
            continue
        schema = media.get("schema")
        content[str(media_type)] = (
            _resolved_schema(document, schema) if isinstance(schema, dict) else {}
        )
    return content


def _security(value: Any) -> list[dict[str, list[str]]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, list[str]]] = []
    for requirement in value:
        if not isinstance(requirement, dict):
            continue
        result.append(
            {str(name): _string_list(scopes) for name, scopes in sorted(requirement.items())}
        )
    return result


def _server_urls(payload: dict[str, Any], specification: str) -> list[str]:
    if specification == "openapi":
        servers = payload.get("servers")
        if not isinstance(servers, list):
            return []
        return [
            str(server["url"])
            for server in servers
            if isinstance(server, dict) and server.get("url")
        ]
    host = str(payload.get("host") or "")
    if not host:
        return []
    base_path = str(payload.get("basePath") or "")
    schemes = _string_list(payload.get("schemes")) or ["https"]
    return [f"{scheme}://{host}{base_path}" for scheme in schemes]


def _resolved_mapping(document: dict[str, Any], value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(key): _resolved_schema(document, item)
        for key, item in sorted(value.items())
        if isinstance(item, dict)
    }


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []
