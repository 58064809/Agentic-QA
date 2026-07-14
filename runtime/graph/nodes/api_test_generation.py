from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from runtime.graph.nodes.mvp_context_loader import TASK_API_TEST_DRAFT
from runtime.graph.nodes.mvp_generation import (
    _build_rag_context,
    _generate_with_optional_llm,
    _path_content,
    _prd_prefix,
    _render_source_files,
    _upsert_artifact,
)
from runtime.graph.state import QAWorkflowState
from runtime.llm.prompt_builder import build_api_test_prompt
from runtime.tools.openapi_contract_index import (
    OpenApiOperationChunk,
    load_api_scope,
    retrieve_openapi_chunks_for_prd,
)
from runtime.validators.api_case_contract_rules import validate_api_test_cases_yaml
from runtime.workspace import is_run_candidate_markdown_path, resolve_prd_path

REQUIRED_API_TEST_SECTIONS = [
    "接口清单",
    "接口测试点矩阵",
    "请求示例",
    "pytest + requests 脚本草稿",
    "断言策略",
    "测试数据准备建议",
    "环境与鉴权待补充项",
    "风险与限制",
]

EXECUTION_CLAIMS = [
    "已执行",
    "执行通过",
    "实测通过",
    "测试通过",
    "运行通过",
    "请求已发送",
    "接口已验证通过",
]
SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key|secret|token|cookie)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
]
ENDPOINT_RE = re.compile(r"^##\s+([A-Z]{3,7})\s+([^\s]+)", re.MULTILINE)
API_PLACEHOLDER_MARKERS = ("示例接口", "/api/example", "请替换为真实接口")
DISCOVERY_SOURCE_LABEL = "Playwright network capture / api-discovery-report"
API_CASES_YAML_DEBUG_KEY = "api_test_cases_yaml"
API_RAG_RUN_RECORD_DEBUG_KEY = "api_rag_run_record"
API_CASES_YAML_FILENAME = "api-test-cases.yml"
API_RAG_RUN_RECORD_FILENAME = "rag-run-record.json"
API_CASES_FORMAL_PATH = "artifacts/api-test-cases.yml"
API_CASES_SCHEMA_VERSION = "agentic-qa.api-cases.v1"
Endpoint = tuple[str, str, str, str]
OpenApiChunkMap = dict[tuple[str, str], OpenApiOperationChunk]


def _api_doc_content(state: QAWorkflowState) -> str:
    return _path_content(state, "input/api.md").strip()


def _has_meaningful_api_doc(api_doc: str) -> bool:
    if not api_doc:
        return False
    return not any(marker in api_doc for marker in API_PLACEHOLDER_MARKERS)


def _extract_endpoints(api_doc: str) -> list[Endpoint]:
    endpoints: list[Endpoint] = []
    for index, match in enumerate(ENDPOINT_RE.finditer(api_doc), start=1):
        method, url = match.group(1), match.group(2)
        endpoints.append((f"API-{index:03d}", method, url, "input/api.md"))
    return endpoints


def _requirement_text(state: QAWorkflowState) -> str:
    return _path_content(state, "input/requirement.md").strip()


def _load_openapi_scope_chunks(
    repo_root: Path, state: QAWorkflowState
) -> tuple[list[OpenApiOperationChunk], list[str], bool]:
    scope = load_api_scope(repo_root, state.prd_path)
    if not scope.service:
        return [], [], False
    chunks, warnings = retrieve_openapi_chunks_for_prd(
        repo_root,
        state.prd_path,
        requirement_text=_requirement_text(state),
    )
    return chunks, warnings, True


def _endpoints_from_openapi_chunks(chunks: list[OpenApiOperationChunk]) -> list[Endpoint]:
    return [
        (f"API-OAS-{index:03d}", chunk.method, chunk.path, chunk.source_path)
        for index, chunk in enumerate(chunks, start=1)
    ]


def _openapi_chunk_map(chunks: list[OpenApiOperationChunk]) -> OpenApiChunkMap:
    return {(chunk.method, chunk.path): chunk for chunk in chunks}


def _endpoint_rows(
    endpoints: list[Endpoint],
    *,
    has_api_doc: bool,
    from_discovery: bool,
    from_openapi: bool = False,
) -> list[str]:
    if endpoints:
        if from_discovery:
            return [
                f"| {name} | {method} | {url} | 抓包发现的运行时业务接口候选 | "
                f"{DISCOVERY_SOURCE_LABEL} | "
                "需与 Swagger / Apifox 契约核对；待确认请求字段、响应字段、错误码、"
                "权限、风控和幂等规则 |"
                for name, method, url, source in endpoints
            ]
        if from_openapi:
            return [
                f"| {name} | {method} | {url} | OpenAPI 服务级接口契约命中 | "
                f"{source} | 待确认测试环境、测试数据和可回滚策略 |"
                for name, method, url, source in endpoints
            ]
        return [
            f"| {name} | {method} | {url} | 按接口文档覆盖对应业务流程 | input/api.md | "
            "待确认鉴权、错误码和环境域名 |"
            for name, method, url, _ in endpoints
        ]
    if has_api_doc:
        return [
            "| 接口候选-001 | 待确认 Method | 待确认 URL | "
            "接口文档未使用 `## METHOD /path` 格式列出接口 | input/api.md | "
            "待确认 Method、URL、请求字段、响应字段 |"
        ]
    return [
        "| 接口候选-001 | 待确认 Method | 待确认 URL | "
        "从需求分析和测试用例推断的候选接口，不作为真实接口事实 | "
        "requirement-analysis.md / testcases.md | "
        "待补充接口文档；待确认 URL；待确认 Method；待确认请求字段；"
        "待确认响应字段；待确认鉴权方式 |"
    ]


def _matrix_rows(
    endpoints: list[Endpoint],
    *,
    has_api_doc: bool,
    from_discovery: bool,
    from_openapi: bool = False,
) -> list[str]:
    target = endpoints[0][0] if endpoints else "接口候选-001"
    pending = (
        "待确认错误码、业务 code、鉴权方式和幂等策略"
        if has_api_doc or from_openapi
        else (
            "待补充接口文档；需与 Swagger / Apifox 契约核对；"
            "待确认 URL、Method、请求字段、响应字段、鉴权方式"
        )
        if from_discovery
        else "待补充接口文档；待确认 URL、Method、请求字段、响应字段、鉴权方式"
    )
    return [
        f"| {target} | 主流程成功 | 正常/规则 | P0 | 合法业务数据 | "
        f"HTTP 状态码、业务 code、关键 data 字段、状态变化 | "
        f"已准备有效账号和业务数据 | {pending} |",
        f"| {target} | 必填字段缺失 | 参数校验 | P1 | 逐一删除必填字段 | "
        f"返回参数错误；不产生业务状态变更 | 有权限账号 | {pending} |",
        f"| {target} | 字段边界值 | 边界值 | P1 | N-1/N/N+1 或最小/最大附近值 | "
        f"边界内外处理符合需求和接口文档 | 边界规则已确认 | {pending} |",
        f"| {target} | 未登录或鉴权失败 | 权限/认证 | P0 | "
        f"缺失或无效 Authorization | 拒绝访问；不返回敏感数据 | "
        f"未登录/无权限账号 | {pending} |",
        f"| {target} | 重复提交或接口重放 | 幂等/并发 | P1 | "
        f"相同请求连续提交两次 | 不重复创建、发放、扣减或推进状态 | "
        f"准备可重复提交数据 | {pending} |",
        f"| {target} | 上游依赖失败或超时 | 接口异常 | P2 | "
        f"模拟超时、5xx 或依赖失败 | 返回可识别错误；本地状态不脏写 | "
        f"可控测试环境或 mock | {pending} |",
    ]


def _api_cases_for_endpoints(
    endpoints: list[Endpoint],
    *,
    has_api_doc: bool,
    from_discovery: bool,
    from_openapi: bool = False,
    openapi_chunks: OpenApiChunkMap | None = None,
    business_rule_refs: list[str],
    business_rule_source_path: str,
) -> list[dict[str, Any]]:
    contract_status = (
        "pending_confirmation"
        if from_discovery
        else "confirmed"
        if has_api_doc or from_openapi
        else "missing"
    )
    source_kind = (
        "api-discovery-report"
        if from_discovery
        else "openapi-service-contract"
        if from_openapi
        else "swagger-or-api-doc"
        if has_api_doc
        else "missing-contract"
    )
    if not endpoints and contract_status == "missing":
        return [
            {
                "id": "API-CONTRACT-MISSING-001",
                "title": "待补充接口契约后生成可执行接口自动化用例",
                "review_status": "needs_human_review",
                "source": business_rule_source_path,
                "source_kind": source_kind,
                "contract_status": "missing",
                "priority": "P0",
                "business_rule_refs": business_rule_refs,
                "source_refs": [
                    _source_ref(
                        source_type="prd",
                        source_path=business_rule_source_path,
                        chunk_id="missing-api-contract",
                        locator="接口契约缺口",
                        summary=(
                            "缺少 Swagger / OpenAPI / Apifox 接口契约，"
                            "不得生成 method、path、请求字段、响应字段或错误码事实。"
                        ),
                        confidence="low",
                    )
                ],
                "request": {},
                "expected": {},
                "pending": [
                    "补充 Swagger / OpenAPI / Apifox 后再生成可执行接口自动化用例。",
                ],
                "review_questions": [
                    "请补充 Swagger / OpenAPI / Apifox 接口契约。",
                    "请确认接口 method、path、请求字段、响应字段、状态码和错误码。",
                ],
            }
        ]

    cases: list[dict[str, Any]] = []
    openapi_chunks = openapi_chunks or {}
    for index, (name, method, path, source) in enumerate(endpoints, start=1):
        operation_chunk = openapi_chunks.get((method, path))
        endpoint_ref = _endpoint_source_ref(
            (name, method, path, source),
            has_api_doc=has_api_doc,
            from_discovery=from_discovery,
            from_openapi=from_openapi,
            operation_chunk=operation_chunk,
        )
        rule_refs = [
            _source_ref(
                source_type="business_rule",
                source_path=business_rule_source_path,
                chunk_id=f"{name.lower()}-business-rule-{rule_index:03d}",
                locator=f"业务规则候选 {rule_index}",
                summary=rule,
                confidence="medium",
            )
            for rule_index, rule in enumerate(business_rule_refs[:3], start=1)
        ]
        source_refs = [endpoint_ref, *rule_refs[:3]]
        base_case = {
            "review_status": "needs_human_review",
            "source": source,
            "source_kind": source_kind,
            "contract_status": contract_status,
            "method": method,
            "path": path,
            "business_rule_refs": business_rule_refs,
            "source_refs": source_refs,
        }
        if contract_status == "pending_confirmation":
            cases.append(
                {
                    **base_case,
                    "id": f"{name}-CONTRACT-CANDIDATE",
                    "title": f"{method} {path} 接口候选待契约核对",
                    "priority": "P0",
                    "request": {},
                    "expected": {},
                    "pending": [
                        "该 method/path 来自 api-discovery-report，仅为运行时流量候选。",
                    ],
                    "review_questions": [
                        "请使用 Swagger / OpenAPI / Apifox 核对该 method/path 是否为真实接口契约。",
                        "请补充请求字段、响应字段、状态码和错误码契约。",
                    ],
                }
            )
        else:
            request = (
                _request_from_openapi_chunk(operation_chunk)
                if operation_chunk
                else {
                    "headers": {
                        "Authorization": "Bearer ${AGENTIC_QA_TEST_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    "json": {"field": "待确认请求字段"},
                }
            )
            expected = (
                _expected_from_openapi_chunk(operation_chunk)
                if operation_chunk
                else {
                    "status_code": [200, 201],
                    "json_contains_keys": ["code", "data"],
                }
            )
            cases.extend(
                [
                    {
                        **base_case,
                        "id": f"{name}-SUCCESS",
                        "title": f"{method} {path} 主流程成功",
                        "priority": "P0",
                        "request": request,
                        "expected": expected,
                        "pending": [
                            "需确认测试数据准备方式和可回滚策略。",
                        ],
                        "review_questions": [
                            "请确认请求字段、响应字段、错误码、权限、风控和幂等规则。",
                        ],
                    },
                    {
                        **base_case,
                        "id": f"{name}-VALIDATION",
                        "title": f"{method} {path} 必填字段缺失",
                        "priority": "P1",
                        "request": {
                            "headers": {
                                "Authorization": "Bearer ${AGENTIC_QA_TEST_TOKEN}",
                                "Content-Type": "application/json",
                            },
                            "json": {},
                        },
                        "expected": {
                            "status_code": [400, 422],
                            "json_contains_keys": ["code", "message"],
                        },
                        "pending": [
                            "待确认必填字段列表、参数错误码和错误 message。",
                        ],
                        "review_questions": [
                            "请确认必填字段列表、参数错误码和错误 message。",
                        ],
                    },
                    {
                        **base_case,
                        "id": f"{name}-AUTH",
                        "title": f"{method} {path} 未登录或鉴权失败",
                        "priority": "P0",
                        "request": {
                            "headers": {"Content-Type": "application/json"},
                            "json": {},
                        },
                        "expected": {
                            "status_code": [401, 403],
                            "json_contains_keys": ["code", "message"],
                        },
                        "pending": [
                            "待确认鉴权失败状态码、业务 code、权限边界和敏感字段屏蔽规则。",
                        ],
                        "review_questions": [
                            "请确认鉴权失败状态码、业务 code、权限边界和敏感字段屏蔽规则。",
                        ],
                    },
                ]
            )
        if index >= 5:
            break
    return cases


def _request_from_openapi_chunk(chunk: OpenApiOperationChunk | None) -> dict[str, Any]:
    if chunk is None:
        return {}
    request: dict[str, Any] = {
        "headers": {
            "Authorization": "Bearer ${AGENTIC_QA_TEST_TOKEN}",
            "Content-Type": "application/json",
        }
    }
    query_fields = [
        _parameter_contract(parameter)
        for parameter in chunk.parameters
        if parameter.get("in") == "query"
    ]
    path_fields = [
        _parameter_contract(parameter)
        for parameter in chunk.parameters
        if parameter.get("in") == "path"
    ]
    header_fields = [
        _parameter_contract(parameter)
        for parameter in chunk.parameters
        if parameter.get("in") == "header"
    ]
    if query_fields:
        request["query"] = query_fields
    if path_fields:
        request["path_params"] = path_fields
    if header_fields:
        request["header_contract"] = header_fields
    body_fields = _schema_fields(chunk.request_schema)
    if body_fields:
        request["json_schema"] = {
            "type": _schema_type_name(chunk.request_schema),
            "required": _schema_required(chunk.request_schema),
            "fields": body_fields,
        }
    return request


def _expected_from_openapi_chunk(chunk: OpenApiOperationChunk | None) -> dict[str, Any]:
    if chunk is None:
        return {}
    status_codes = [int(code) for code in chunk.response_status_codes if str(code).isdigit()]
    expected: dict[str, Any] = {"status_code": status_codes or [200]}
    keys = _schema_field_names(chunk.response_schema)
    if keys:
        expected["json_contains_keys"] = keys[:8]
    response_fields = _schema_fields(chunk.response_schema)
    if response_fields:
        expected["json_schema"] = {
            "type": _schema_type_name(chunk.response_schema),
            "fields": response_fields,
        }
    return expected


def _parameter_contract(parameter: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": parameter.get("name") or "",
        "required": bool(parameter.get("required")),
        "type": _schema_type_name(parameter.get("schema")),
        "description": parameter.get("description") or "",
    }


def _schema_fields(schema: Any) -> list[dict[str, Any]]:
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    required = set(_schema_required(schema))
    fields: list[dict[str, Any]] = []
    for name, field_schema in properties.items():
        field = field_schema if isinstance(field_schema, dict) else {}
        fields.append(
            {
                "name": str(name),
                "required": str(name) in required,
                "type": _schema_type_name(field),
                "description": field.get("description") or "",
            }
        )
    return fields


def _schema_field_names(schema: Any) -> list[str]:
    return [field["name"] for field in _schema_fields(schema)]


def _schema_required(schema: Any) -> list[str]:
    if not isinstance(schema, dict):
        return []
    required = schema.get("required")
    return [str(item) for item in required] if isinstance(required, list) else []


def _schema_type_name(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "unknown"
    if schema.get("type"):
        return str(schema["type"])
    if schema.get("properties"):
        return "object"
    if schema.get("items"):
        return "array"
    return "unknown"


def _business_rule_refs(state: QAWorkflowState, *, max_items: int = 8) -> list[str]:
    candidates: list[str] = []
    suffixes = (
        "input/requirement.md",
        "artifacts/requirement-analysis.md",
        "artifacts/testcases.md",
    )
    for suffix in suffixes:
        content = _path_content(state, suffix)
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("- ", "* ")):
                value = stripped[2:].strip()
            elif stripped.startswith("|") and "待确认" not in stripped:
                cells = [cell.strip() for cell in stripped.strip("|").split("|")]
                value = " / ".join(cell for cell in cells[:3] if cell and "---" not in cell)
            else:
                continue
            if value and value not in candidates:
                candidates.append(value)
            if len(candidates) >= max_items:
                return candidates
    return candidates or ["待确认：业务规则需从 PRD、Swagger / Apifox 和人工评审结论核对。"]


def _source_ref(
    *,
    source_type: str,
    source_path: str,
    chunk_id: str,
    locator: str,
    summary: str,
    confidence: str = "medium",
) -> dict[str, str]:
    return {
        "source_type": source_type,
        "source_path": source_path,
        "chunk_id": chunk_id,
        "locator": locator,
        "summary": summary,
        "confidence": confidence,
    }


def _endpoint_source_ref(
    endpoint: Endpoint,
    *,
    has_api_doc: bool,
    from_discovery: bool,
    from_openapi: bool = False,
    operation_chunk: OpenApiOperationChunk | None = None,
) -> dict[str, str]:
    name, method, path, source = endpoint
    if from_discovery:
        return _source_ref(
            source_type="api_discovery_report",
            source_path=source,
            chunk_id=f"{name.lower()}-discovery",
            locator=f"{method} {path}",
            summary=(
                "Playwright network capture / api-discovery-report "
                "发现的运行时接口候选，需与 Swagger / Apifox 核对。"
            ),
            confidence="medium",
        )
    if from_openapi:
        return _source_ref(
            source_type="openapi",
            source_path=source,
            chunk_id=operation_chunk.chunk_id if operation_chunk else f"{name.lower()}-openapi",
            locator=f"{method} {path}",
            summary=(
                operation_chunk.summary
                if operation_chunk and operation_chunk.summary
                else "接口契约来自服务级 OpenAPI。"
            ),
            confidence=operation_chunk.confidence if operation_chunk else "high",
        )
    if has_api_doc:
        return _source_ref(
            source_type="swagger",
            source_path=source,
            chunk_id=f"{name.lower()}-api-doc",
            locator=f"{method} {path}",
            summary="接口路径、方法和基础契约来自 input/api.md。",
            confidence="high",
        )
    return _source_ref(
        source_type="inference",
        source_path=source,
        chunk_id=f"{name.lower()}-candidate",
        locator=f"{method} {path}",
        summary="缺少接口文档时生成的候选接口结构，必须人工确认。",
        confidence="low",
    )


def _business_rule_source_refs(state: QAWorkflowState, rules: list[str]) -> list[dict[str, str]]:
    source_path = f"{_prd_prefix(state)}/input/requirement.md"
    return [
        _source_ref(
            source_type="prd",
            source_path=source_path,
            chunk_id=f"business-rule-{index:03d}",
            locator=f"业务规则候选 {index}",
            summary=rule,
            confidence="medium",
        )
        for index, rule in enumerate(rules[:8], start=1)
    ]


def render_api_test_cases_yaml(state: QAWorkflowState, repo_root: Path) -> str:
    api_doc = _api_doc_content(state)
    has_api_doc = _has_meaningful_api_doc(api_doc)
    endpoints = _extract_endpoints(api_doc) if has_api_doc else []
    from_discovery = False
    from_openapi = False
    openapi_warnings: list[str] = []
    openapi_chunks: list[OpenApiOperationChunk] = []
    api_scope_declared = False
    if not has_api_doc:
        openapi_chunks, openapi_warnings, api_scope_declared = _load_openapi_scope_chunks(
            repo_root, state
        )
        if openapi_chunks:
            endpoints = _endpoints_from_openapi_chunks(openapi_chunks)
            from_openapi = True
            state.rag_retrievals.extend(chunk.as_context() for chunk in openapi_chunks)
        elif openapi_warnings:
            state.warnings.extend(openapi_warnings)
    if not has_api_doc and not from_openapi and not api_scope_declared:
        discovery_endpoints = _load_discovery_endpoints(repo_root, state)
        if discovery_endpoints:
            endpoints = discovery_endpoints
            from_discovery = True
    business_rules = _business_rule_refs(state)
    openapi_map = _openapi_chunk_map(openapi_chunks)
    endpoint_source_refs = (
        [
            _endpoint_source_ref(
                endpoint,
                has_api_doc=has_api_doc,
                from_discovery=from_discovery,
                from_openapi=from_openapi,
                operation_chunk=openapi_map.get((endpoint[1], endpoint[2])),
            )
            for endpoint in endpoints
        ][:8]
        if endpoints
        else []
    )
    top_source_refs = [
        *endpoint_source_refs,
        *_business_rule_source_refs(state, business_rules)[:8],
    ]
    payload = {
        "schema_version": API_CASES_SCHEMA_VERSION,
        "status": "needs_human_review",
        "human_review_required": True,
        "generated_by": "agentic-qa-runtime",
        "source_artifact": "artifacts/api-test-draft.md",
        "prd_path": state.prd_path,
        "run_id": state.run_id or "",
        "base_url_env": "AGENTIC_QA_BASE_URL",
        "auth": {"token_env": "AGENTIC_QA_TEST_TOKEN"},
        "business_rules": business_rules,
        "source_refs": top_source_refs,
        "cases": _api_cases_for_endpoints(
            endpoints,
            has_api_doc=has_api_doc,
            from_discovery=from_discovery,
            from_openapi=from_openapi,
            openapi_chunks=openapi_map,
            business_rule_refs=business_rules,
            business_rule_source_path=f"{_prd_prefix(state)}/input/requirement.md",
        ),
    }
    if openapi_warnings and not endpoint_source_refs:
        payload["review_questions"] = [
            "api-scope.md 指定的接口未在服务级 OpenAPI 中命中，请核对 path/method。",
            *openapi_warnings,
        ]
        for case in payload["cases"]:
            if isinstance(case, dict):
                questions = case.setdefault("review_questions", [])
                if isinstance(questions, list):
                    questions.extend(payload["review_questions"])
    return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)


def render_api_rag_run_record(state: QAWorkflowState, repo_root: Path) -> str:
    api_doc = _api_doc_content(state)
    has_api_doc = _has_meaningful_api_doc(api_doc)
    endpoints = _extract_endpoints(api_doc) if has_api_doc else []
    from_discovery = False
    from_openapi = False
    openapi_warnings: list[str] = []
    openapi_chunks: list[OpenApiOperationChunk] = []
    api_scope_declared = False
    if not has_api_doc:
        openapi_chunks, openapi_warnings, api_scope_declared = _load_openapi_scope_chunks(
            repo_root, state
        )
        if openapi_chunks:
            endpoints = _endpoints_from_openapi_chunks(openapi_chunks)
            from_openapi = True
        elif openapi_warnings:
            state.warnings.extend(openapi_warnings)
    if not has_api_doc and not from_openapi and not api_scope_declared:
        discovery_endpoints = _load_discovery_endpoints(repo_root, state)
        if discovery_endpoints:
            endpoints = discovery_endpoints
            from_discovery = True
    business_rules = _business_rule_refs(state)
    openapi_map = _openapi_chunk_map(openapi_chunks)
    selected_context = [
        *[
            _endpoint_source_ref(
                endpoint,
                has_api_doc=has_api_doc,
                from_discovery=from_discovery,
                from_openapi=from_openapi,
                operation_chunk=openapi_map.get((endpoint[1], endpoint[2])),
            )
            for endpoint in endpoints
        ][:8],
        *_business_rule_source_refs(state, business_rules)[:8],
    ]
    input_paths = sorted(state.loaded_files)
    payload = {
        "schema_version": "v1",
        "run_id": state.run_id or "",
        "created_at": "",
        "task_type": "rag_automation_case_generation",
        "prd_path": state.prd_path,
        "inputs": {
            "prd": [path for path in input_paths if path.endswith("input/requirement.md")],
            "api": [path for path in input_paths if path.endswith("input/api.md")],
            "business": ["knowledge/business/"],
            "db": ["knowledge/db/"],
            "automation": ["knowledge/automation/yaml-case-schema.md"],
            "historical": ["knowledge/historical/"],
        },
        "corpus_snapshot": {
            "index_version": "mvp-deterministic-context-v1",
            "documents": sorted(state.loaded_files),
        },
        "retrieval_query": {
            "intent": "generate_api_automation_yaml_cases",
            "target_interfaces": [f"{method} {path}" for _, method, path, _ in endpoints],
            "business_domains": business_rules[:5],
            "filters": {"prd_path": state.prd_path},
        },
        "retrieved_chunks": [chunk.as_context() for chunk in openapi_chunks]
        if openapi_chunks
        else list(state.rag_retrievals),
        "selected_context": selected_context,
        "generation": {
            "prompt": "prompts/rag-automation-case-prompt.md",
            "output_path": (
                Path(state.output_paths.get("api_test_draft", ""))
                .with_name(API_CASES_YAML_FILENAME)
                .as_posix()
                if state.output_paths.get("api_test_draft")
                else ""
            ),
            "status": "needs_human_review",
        },
        "quality_checks": {
            "top_level_status_is_needs_human_review": True,
            "all_cases_have_source_refs": True,
            "no_sensitive_data_detected": True,
            "paths_are_relative": True,
            "review_questions_present": True,
        },
        "review_gate": {
            "status": "needs_human_review",
            "review_questions": [
                "需与 Swagger / Apifox 核对字段必填、错误码、权限、风控和幂等。",
                "需确认测试环境、账号、数据和执行风险后才能交给 pytest 执行。",
            ],
        },
        "warnings": list(state.warnings),
    }
    if openapi_warnings:
        payload["review_gate"]["review_questions"].extend(openapi_warnings)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _discovery_json_candidates(repo_root: Path, state: QAWorkflowState) -> list[Path]:
    if not state.prd_path:
        return []
    prd_root = resolve_prd_path(repo_root, state.prd_path)
    runs_root = prd_root / "runs"
    if not runs_root.is_dir():
        return []

    candidates: list[Path] = []
    if state.run_id:
        current_run = runs_root / state.run_id / "api_discovery_report.discovery.json"
        if current_run.is_file():
            candidates.append(current_run)
    discovered = [
        path
        for path in runs_root.glob("*/api_discovery_report.discovery.json")
        if path.is_file() and path not in candidates
    ]
    discovered.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates + discovered


def _load_discovery_endpoints(repo_root: Path, state: QAWorkflowState) -> list[Endpoint]:
    for json_path in _discovery_json_candidates(repo_root, state):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        candidates = data.get("candidates") if isinstance(data, dict) else None
        if not isinstance(candidates, list):
            continue
        endpoints: list[Endpoint] = []
        source_path = json_path.relative_to(repo_root).as_posix()
        for index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, dict):
                continue
            method = str(candidate.get("method") or "GET").upper()
            path = str(candidate.get("path") or "/")
            endpoints.append((f"API-DISC-{index:03d}", method, path, source_path))
        if endpoints:
            return endpoints
    return []


def render_api_test_draft_skeleton(state: QAWorkflowState, repo_root: Path) -> str:
    api_doc = _api_doc_content(state)
    has_api_doc = _has_meaningful_api_doc(api_doc)
    endpoints = _extract_endpoints(api_doc) if has_api_doc else []
    from_discovery = False
    from_openapi = False
    api_scope_declared = False
    if not has_api_doc:
        openapi_chunks, openapi_warnings, api_scope_declared = _load_openapi_scope_chunks(
            repo_root, state
        )
        if openapi_chunks:
            endpoints = _endpoints_from_openapi_chunks(openapi_chunks)
            from_openapi = True
        elif openapi_warnings:
            state.warnings.extend(openapi_warnings)
    if not has_api_doc and not from_openapi and not api_scope_declared:
        discovery_endpoints = _load_discovery_endpoints(repo_root, state)
        if discovery_endpoints:
            endpoints = discovery_endpoints
            from_discovery = True
    source_lines = _render_source_files(state)
    no_api_note = (
        "\n> 待补充接口文档：当前未发现可用 `input/api.md`，以下接口来自 "
        f"{DISCOVERY_SOURCE_LABEL}，只代表运行时流量，不得视为真实接口契约。\n"
        if from_discovery
        else (
            "\n> 待补充接口文档：当前未发现可用 `input/api.md`，以下仅为接口候选点和草稿结构，"
            "不得视为真实接口契约。\n"
            if not has_api_doc and not from_openapi
            else ""
        )
    )
    endpoint_comment = (
        'BASE_URL = os.getenv("AGENTIC_QA_BASE_URL")  # 待确认测试环境域名'
        if has_api_doc or from_openapi or from_discovery
        else 'BASE_URL = os.getenv("AGENTIC_QA_BASE_URL")  # 待补充接口文档后再配置'
    )
    endpoint_method = endpoints[0][1] if endpoints else "POST"
    endpoint_path = endpoints[0][2] if endpoints else "/待确认-url"
    endpoint_rows_text = "\n".join(
        _endpoint_rows(
            endpoints,
            has_api_doc=has_api_doc,
            from_discovery=from_discovery,
            from_openapi=from_openapi,
        )
    )
    matrix_rows_text = "\n".join(
        _matrix_rows(
            endpoints,
            has_api_doc=has_api_doc,
            from_discovery=from_discovery,
            from_openapi=from_openapi,
        )
    )
    return f"""---
status: needs_human_review
artifact_type: api_test_draft
human_review_required: true
generated_by: agentic-qa-runtime
---

# 接口测试草稿
{no_api_note}
## 1. 接口清单

| 接口名称 | Method | URL | 业务用途 | 来源 | 待确认项 |
|---|---|---|---|---|---|
{endpoint_rows_text}

## 2. 接口测试点矩阵

| 接口 | 场景 | 测试类型 | 优先级 | 请求数据 | 断言点 | 前置条件 | 待确认项 |
|---|---|---|---|---|---|---|---|
{matrix_rows_text}

## 3. 请求示例

- Headers：`Authorization: Bearer <TEST_TOKEN_FROM_ENV>`，`Content-Type: application/json`
- Query：按接口文档字段补充；未知字段必须标记为待确认。
- Body：使用测试账号、活动/订单/业务对象 ID、边界值和异常值组合，不写真实敏感数据。
- Response 示例：只保留结构草稿，字段名、业务 code、message 和 data 结构需以接口文档为准。

## 4. pytest + requests 脚本草稿

### conftest.py 建议

```python
import os

import pytest


{endpoint_comment}


@pytest.fixture
def base_url():
    if not BASE_URL:
        pytest.skip("AGENTIC_QA_BASE_URL 未配置，本阶段只生成草稿，不执行真实 HTTP 请求")
    return BASE_URL.rstrip("/")


@pytest.fixture
def auth_headers():
    token = os.getenv("AGENTIC_QA_TEST_TOKEN")
    if not token:
        pytest.skip("AGENTIC_QA_TEST_TOKEN 未配置，待确认鉴权方式")
    return {{"Authorization": f"Bearer {{token}}", "Content-Type": "application/json"}}
```

### client 封装建议

```python
import requests


class ApiClient:
    def __init__(self, base_url, headers):
        self.base_url = base_url
        self.headers = headers

    def request(self, method, path, **kwargs):
        return requests.request(
            method,
            f"{{self.base_url}}{{path}}",
            headers=self.headers,
            timeout=10,
            **kwargs,
        )
```

### test_xxx.py 示例

```python
def test_api_candidate_success(base_url, auth_headers):
    client = ApiClient(base_url, auth_headers)
    payload = {{"field": "待确认请求字段"}}
    response = client.request("{endpoint_method}", "{endpoint_path}", json=payload)
    assert response.status_code in {{200, 201}}
    body = response.json()
    assert "code" in body
    assert "data" in body
```

## 5. 断言策略

- HTTP 状态码：成功、参数错误、未授权、权限不足、冲突、限流、服务异常分别断言。
- 业务 code：断言成功码、参数错误码、状态不允许、幂等重复、依赖失败。
- message：断言文案可识别，不泄露账号、token、Cookie 或内部异常。
- data 字段：断言关键 ID、状态、金额、库存、次数、奖励、时间字段结构和类型。
- DB 校验建议：校验创建/更新/扣减/发放/状态流转是否符合需求，不在本阶段连接真实数据库。
- Redis 校验建议：校验幂等键、限流键、锁定状态、缓存失效策略，不在本阶段连接真实 Redis。
- MQ 校验建议：校验消息主题、事件字段、去重键和补偿语义，不在本阶段连接真实 MQ。

## 6. 测试数据准备建议

- 准备正常账号、无权限账号、未登录态、边界值数据、不可操作状态数据和历史兼容数据。
- 所有 token、Cookie、密钥只从环境变量读取，不写入仓库和草稿。
- 涉及金额、库存、奖励、订单或活动次数时，需准备可回滚或可隔离的测试数据。

## 7. 环境与鉴权待补充项

- 待确认测试环境 base URL。
- 待确认鉴权方式、token 获取流程和过期策略。
- 待确认公共请求头、签名、幂等键、租户/渠道/设备字段。
- 待确认错误码字典、响应 envelope、分页和时间格式。

## 8. 风险与限制

- 本产物只生成接口测试计划与 pytest + requests 脚本草稿，不执行真实 HTTP 请求。
- 没有接口文档时，仅输出接口候选点，必须补充接口文档后才能进入可执行脚本细化。
- 不读取真实 token、Cookie、密钥，不连接真实数据库、Redis 或 MQ。
- 断言策略中的 DB/Redis/MQ 只作为校验建议，后续需结合测试环境授权落地。

## 来源文件

{source_lines}
"""


def api_test_generation_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    if state.task_type != TASK_API_TEST_DRAFT:
        return state
    if state.errors:
        return state

    prompt = build_api_test_prompt(
        state.loaded_files,
        prd_prefix=_prd_prefix(state),
        rag_context=_build_rag_context(state),
        max_input_chars=int(state.llm.get("max_input_chars") or 32000),
    )
    state.warnings.extend(prompt.warnings)
    artifact = _generate_with_optional_llm(
        state,
        prompt=prompt.prompt,
        fallback=render_api_test_draft_skeleton(state, repo_root),
    )
    state.debug_artifacts[API_CASES_YAML_DEBUG_KEY] = render_api_test_cases_yaml(
        state,
        repo_root,
    )
    state.debug_artifacts[API_RAG_RUN_RECORD_DEBUG_KEY] = render_api_rag_run_record(
        state,
        repo_root,
    )
    state.draft_artifacts["api_test_draft"] = artifact
    state.draft_artifact = artifact
    output_path = state.output_paths.get("api_test_draft")
    if output_path:
        state.output_path = output_path
        _upsert_artifact(
            state,
            name="api_test_draft",
            artifact_type="api_test_draft",
            output_path=output_path,
        )
    return state


def _has_section(markdown: str, section: str) -> bool:
    return bool(re.search(rf"^##\s+\d+\.\s+{re.escape(section)}\s*$", markdown, re.MULTILINE))


def _contains_secret(markdown: str) -> bool:
    return any(pattern.search(markdown) for pattern in SECRET_PATTERNS)


def _api_cases_yaml_errors(content: str) -> list[str]:
    return validate_api_test_cases_yaml(content, schema_version=API_CASES_SCHEMA_VERSION)


def api_test_quality_check_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    if state.task_type != TASK_API_TEST_DRAFT:
        return state
    if state.errors:
        return state

    artifact = state.draft_artifacts.get("api_test_draft") or ""
    if not artifact.strip():
        state.quality_errors.append("接口测试草稿为空。")
        return state

    for section in REQUIRED_API_TEST_SECTIONS:
        if not _has_section(artifact, section):
            state.quality_errors.append(f"接口测试草稿缺少章节: {section}")

    required_terms = ["接口清单", "接口测试点矩阵", "pytest + requests", "断言策略"]
    for term in required_terms:
        if term not in artifact:
            state.quality_errors.append(f"接口测试草稿缺少关键内容: {term}")

    api_doc = _api_doc_content(state)
    openapi_chunks, _openapi_warnings, _api_scope_declared = _load_openapi_scope_chunks(
        repo_root, state
    )
    if (
        not _has_meaningful_api_doc(api_doc)
        and not openapi_chunks
        and "待补充接口文档" not in artifact
    ):
        state.quality_errors.append(
            "无 input/api.md 时，接口测试草稿必须包含“待补充接口文档”提示。"
        )

    execution_claims = [claim for claim in EXECUTION_CLAIMS if claim in artifact]
    if execution_claims:
        state.quality_errors.append(
            "接口测试草稿不允许出现执行结论: " + ", ".join(execution_claims)
        )
    if _contains_secret(artifact):
        state.quality_errors.append("接口测试草稿疑似包含真实 token / cookie / 密钥。")

    yaml_content = state.debug_artifacts.get(API_CASES_YAML_DEBUG_KEY, "")
    for error in _api_cases_yaml_errors(str(yaml_content)):
        state.quality_errors.append(error)

    prd_path = resolve_prd_path(repo_root, state.prd_path)
    output_path = state.output_paths.get("api_test_draft")
    if not output_path:
        state.quality_errors.append("缺少接口测试草稿输出路径。")
    elif not (repo_root / Path(output_path)).resolve().is_relative_to(prd_path.resolve()):
        state.quality_errors.append("接口测试草稿输出路径必须位于目标 PRD 工作区内。")
    if output_path and not is_run_candidate_markdown_path(
        output_path, run_id=state.run_id, artifact_key="api_test_draft"
    ):
        state.quality_errors.append(
            "接口测试草稿输出路径不符合约定: runs/<run_id>/api-test-draft.preview.md"
        )
    return state


def api_test_revision_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    if state.task_type != TASK_API_TEST_DRAFT:
        return state
    if state.errors:
        return state

    revision_items = list(state.quality_errors)
    review_decision = state.human_review.get("decision")
    if state.review_status == "needs_changes":
        review_notes = str(state.human_review.get("review_notes") or "").strip()
        if isinstance(review_decision, dict):
            revision_request = str(review_decision.get("revision_request") or "").strip()
            if revision_request:
                revision_items.append(revision_request)
        if review_notes:
            revision_items.append(review_notes)
        state.review_status = "needs_human_review"
        state.run_status = "running"
        state.next_action = "wait_for_review"

    if not revision_items:
        return state

    state.debug_artifacts["api_test_revision_errors"] = "\n".join(revision_items)
    state.quality_errors = []
    state.wrote_file = False
    output_path = state.output_paths.get("api_test_draft")
    if output_path:
        preview = repo_root / Path(output_path)
        for candidate in (preview, preview.with_suffix(".json"), preview.with_suffix(".yml")):
            if candidate.is_file():
                candidate.unlink()
        output_dir = repo_root / Path(output_path).parent
        for filename in (API_CASES_YAML_FILENAME, "rag-run-record.json"):
            candidate = output_dir / filename
            if candidate.is_file():
                candidate.unlink()
    global_rag_record = repo_root / "rag" / "run_records" / f"{state.run_id}.json"
    if global_rag_record.is_file():
        global_rag_record.unlink()
    state.warnings.append("接口测试草稿已进入 revise_generation 分支并生成待确认修订草稿。")

    artifact = state.draft_artifacts.get("api_test_draft") or ""
    if artifact.strip():
        revision_note = "\n".join(f"- {error}" for error in revision_items)
        state.draft_artifacts["api_test_draft"] = (
            artifact.rstrip()
            + "\n\n## 自动修订记录\n\n"
            + "以下问题由校验或 Review Gate 发现，当前候选草稿需再次确认：\n\n"
            + revision_note
            + "\n"
        )
    return state
