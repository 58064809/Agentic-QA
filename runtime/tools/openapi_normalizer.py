from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


@dataclass(frozen=True)
class ApiParameter:
    name: str
    location: str
    required: bool = False
    schema: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class ApiEndpoint:
    operation_id: str
    name: str
    method: str
    path: str
    summary: str
    description: str
    tags: list[str]
    parameters: list[ApiParameter]
    request_body_schema: dict[str, Any]
    response_schema: dict[str, Any]
    success_codes: list[str]
    error_codes: list[str]
    auth_requirements: list[str]
    apifox_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedApiDocument:
    title: str
    version: str
    spec_type: str
    endpoints: list[ApiEndpoint]
    security_schemes: dict[str, Any]
    source_path: str = ""
    warnings: list[str] = field(default_factory=list)


def normalize_openapi_document(
    payload: dict[str, Any], *, source_path: str = ""
) -> NormalizedApiDocument:
    if not isinstance(payload, dict):
        raise ValueError("OpenAPI 文档必须是对象")
    spec_type = _detect_spec_type(payload)
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    title = str(info.get("title") or "API 文档")
    version = str(info.get("version") or "")
    security_schemes = _security_schemes(payload, spec_type)
    global_security = payload.get("security") if isinstance(payload.get("security"), list) else []
    paths = payload.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError("接口文档无可用 paths")

    endpoints: list[ApiEndpoint] = []
    warnings: list[str] = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        common_parameters = _parameters(path_item.get("parameters"), payload)
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            endpoint = _endpoint_from_operation(
                payload,
                spec_type=spec_type,
                path=str(path),
                method=method.upper(),
                operation=operation,
                common_parameters=common_parameters,
                security_schemes=security_schemes,
                global_security=global_security,
            )
            endpoints.append(endpoint)
    if not endpoints:
        raise ValueError("接口文档 paths 中没有可用 HTTP operation")
    return NormalizedApiDocument(
        title=title,
        version=version,
        spec_type=spec_type,
        endpoints=endpoints,
        security_schemes=security_schemes,
        source_path=source_path,
        warnings=warnings,
    )


def render_openapi_markdown(document: NormalizedApiDocument) -> str:
    lines = [
        "# API 文档归一化结果",
        "",
        "## 来源",
        "",
        f"- 标题：{document.title}",
        f"- 版本：{document.version or '未提供'}",
        f"- 类型：{document.spec_type}",
        f"- 源文件：`{document.source_path or 'input/api.openapi'}`",
        "",
        "## 接口清单",
        "",
        "| Method | Path | Name | Tags | Auth | Summary |",
        "|---|---|---|---|---|---|",
    ]
    for endpoint in document.endpoints:
        lines.append(
            "| "
            + " | ".join(
                [
                    endpoint.method,
                    endpoint.path,
                    endpoint.name or endpoint.operation_id,
                    ", ".join(endpoint.tags) or "未分组",
                    ", ".join(endpoint.auth_requirements) or "无/待确认",
                    endpoint.summary or endpoint.description or "待补充",
                ]
            )
            + " |"
        )

    for endpoint in document.endpoints:
        lines.extend(["", f"## {endpoint.method} {endpoint.path}", ""])
        lines.extend(
            [
                "### 基本信息",
                "",
                f"- OperationId：`{endpoint.operation_id}`",
                f"- 名称：{endpoint.name}",
                f"- Tags：{', '.join(endpoint.tags) or '未分组'}",
                f"- 鉴权：{', '.join(endpoint.auth_requirements) or '无/待确认'}",
                f"- Summary：{endpoint.summary or '未提供'}",
                f"- Description：{endpoint.description or '未提供'}",
                "",
            ]
        )
        lines.extend(_render_parameter_section("请求头", endpoint.parameters, "header"))
        lines.extend(_render_parameter_section("Query 参数", endpoint.parameters, "query"))
        lines.extend(_render_parameter_section("Path 参数", endpoint.parameters, "path"))
        lines.extend(["### Request Body", ""])
        lines.extend(_render_schema(endpoint.request_body_schema))
        lines.extend(["", "### Response", ""])
        lines.append(f"- 成功状态码：{', '.join(endpoint.success_codes) or '待确认'}")
        lines.append(f"- 错误状态码：{', '.join(endpoint.error_codes) or '待确认'}")
        lines.extend(_render_schema(endpoint.response_schema))
        lines.extend(
            [
                "",
                "### 错误码",
                "",
                "- 以 responses 中 4xx/5xx 状态码和业务 code 字段为准。",
                "",
                "### 待确认项",
                "",
                "- [ ] 确认测试环境 base URL、鉴权获取方式和公共请求头。",
                "- [ ] 确认业务 code、message、data envelope 的统一结构。",
                "- [ ] 确认幂等键、限流、DB/Redis/MQ 校验口径。",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def required_schema_fields(schema: dict[str, Any]) -> list[str]:
    required = schema.get("required")
    return [str(item) for item in required] if isinstance(required, list) else []


def _detect_spec_type(payload: dict[str, Any]) -> str:
    if payload.get("openapi"):
        return f"openapi-{payload['openapi']}"
    if payload.get("swagger"):
        return f"swagger-{payload['swagger']}"
    raise ValueError("不是可识别的 Swagger / OpenAPI 文档")


def _security_schemes(payload: dict[str, Any], spec_type: str) -> dict[str, Any]:
    if spec_type.startswith("swagger-"):
        definitions = payload.get("securityDefinitions")
        return definitions if isinstance(definitions, dict) else {}
    components = payload.get("components")
    if not isinstance(components, dict):
        return {}
    schemes = components.get("securitySchemes")
    return schemes if isinstance(schemes, dict) else {}


def _endpoint_from_operation(
    root: dict[str, Any],
    *,
    spec_type: str,
    path: str,
    method: str,
    operation: dict[str, Any],
    common_parameters: list[ApiParameter],
    security_schemes: dict[str, Any],
    global_security: list[Any],
) -> ApiEndpoint:
    fallback_operation_id = f"{method.lower()}_{path.strip('/').replace('/', '_')}"
    operation_id = str(operation.get("operationId") or fallback_operation_id)
    tags = [str(tag) for tag in operation.get("tags", []) if tag]
    parameters = [*common_parameters, *_parameters(operation.get("parameters"), root)]
    request_body_schema = _request_body_schema(operation, root, spec_type)
    response_schema, success_codes, error_codes = _response_schema_and_codes(operation, root)
    security = operation.get("security")
    if not isinstance(security, list):
        security = global_security
    auth_requirements = _auth_requirements(security, security_schemes)
    return ApiEndpoint(
        operation_id=operation_id,
        name=str(operation.get("summary") or operation_id),
        method=method,
        path=path,
        summary=str(operation.get("summary") or ""),
        description=str(operation.get("description") or ""),
        tags=tags,
        parameters=parameters,
        request_body_schema=request_body_schema,
        response_schema=response_schema,
        success_codes=success_codes,
        error_codes=error_codes,
        auth_requirements=auth_requirements,
        apifox_metadata=_apifox_metadata(operation),
    )


def _parameters(value: Any, root: dict[str, Any]) -> list[ApiParameter]:
    if not isinstance(value, list):
        return []
    parameters: list[ApiParameter] = []
    for item in value:
        parameter = _resolve_ref(item, root)
        if not isinstance(parameter, dict):
            continue
        schema = _resolve_ref(parameter.get("schema"), root)
        parameters.append(
            ApiParameter(
                name=str(parameter.get("name") or ""),
                location=str(parameter.get("in") or ""),
                required=bool(parameter.get("required")),
                schema=schema if isinstance(schema, dict) else {},
                description=str(parameter.get("description") or ""),
            )
        )
    return parameters


def _request_body_schema(
    operation: dict[str, Any], root: dict[str, Any], spec_type: str
) -> dict[str, Any]:
    if spec_type.startswith("swagger-"):
        for parameter in _parameters(operation.get("parameters"), root):
            if parameter.location == "body":
                return _resolve_ref(parameter.schema, root)
        return {}
    request_body = _resolve_ref(operation.get("requestBody"), root)
    if not isinstance(request_body, dict):
        return {}
    content = request_body.get("content")
    if not isinstance(content, dict):
        return {}
    media = content.get("application/json") or next(iter(content.values()), {})
    if not isinstance(media, dict):
        return {}
    schema = _resolve_ref(media.get("schema"), root)
    return schema if isinstance(schema, dict) else {}


def _response_schema_and_codes(
    operation: dict[str, Any], root: dict[str, Any]
) -> tuple[dict[str, Any], list[str], list[str]]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return {}, [], []
    success_codes = [str(code) for code in responses if str(code).startswith(("2", "3"))]
    error_codes = [str(code) for code in responses if str(code).startswith(("4", "5"))]
    selected_code = success_codes[0] if success_codes else next(iter(responses), "")
    response = _resolve_ref(responses.get(selected_code), root)
    if not isinstance(response, dict):
        return {}, success_codes, error_codes
    content = response.get("content")
    if isinstance(content, dict):
        media = content.get("application/json") or next(iter(content.values()), {})
        if isinstance(media, dict):
            schema = _resolve_ref(media.get("schema"), root)
            return schema if isinstance(schema, dict) else {}, success_codes, error_codes
    schema = _resolve_ref(response.get("schema"), root)
    return schema if isinstance(schema, dict) else {}, success_codes, error_codes


def _auth_requirements(security: list[Any], security_schemes: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in security:
        if not isinstance(item, dict):
            continue
        for name in item:
            if name in security_schemes:
                names.append(str(name))
    return list(dict.fromkeys(names))


def _resolve_ref(value: Any, root: dict[str, Any]) -> Any:
    if not isinstance(value, dict):
        return value
    ref = value.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return value
    current: Any = root
    for part in ref.removeprefix("#/").split("/"):
        if not isinstance(current, dict):
            return value
        current = current.get(part)
    return current if current is not None else value


def _schema_type(schema: dict[str, Any]) -> str:
    schema = _resolve_ref(schema, {})
    value = schema.get("type") if isinstance(schema, dict) else None
    if value:
        return str(value)
    if isinstance(schema, dict) and schema.get("properties"):
        return "object"
    return "待确认"


def _render_parameter_section(
    title: str, parameters: list[ApiParameter], location: str
) -> list[str]:
    selected = [parameter for parameter in parameters if parameter.location == location]
    lines = [f"### {title}", ""]
    if not selected:
        return [*lines, "- 无或待确认。", ""]
    lines.extend(["| Name | Required | Type | Description |", "|---|---|---|---|"])
    for parameter in selected:
        lines.append(
            f"| {parameter.name} | {parameter.required} | {_schema_type(parameter.schema)} | "
            f"{parameter.description or '待补充'} |"
        )
    lines.append("")
    return lines


def _render_schema(schema: dict[str, Any]) -> list[str]:
    if not schema:
        return ["- 无 schema 或待确认。"]
    required = set(required_schema_fields(schema))
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return [f"- Schema 类型：{_schema_type(schema)}"]
    lines = ["| Field | Required | Type | Description |", "|---|---|---|---|"]
    for name, raw in properties.items():
        field_schema = raw if isinstance(raw, dict) else {}
        lines.append(
            f"| {name} | {str(name) in required} | {_schema_type(field_schema)} | "
            f"{field_schema.get('description') or '待补充'} |"
        )
    return lines


def _apifox_metadata(operation: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in operation.items()
        if isinstance(key, str) and key.startswith("x-apifox")
    }
