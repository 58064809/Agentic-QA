from __future__ import annotations

import json
import re
from pathlib import Path

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
from runtime.workspace import resolve_prd_path

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
Endpoint = tuple[str, str, str, str]


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


def _endpoint_rows(
    endpoints: list[Endpoint],
    *,
    has_api_doc: bool,
    from_discovery: bool,
) -> list[str]:
    if endpoints:
        if from_discovery:
            return [
                f"| {name} | {method} | {url} | 抓包发现的运行时业务接口候选 | {source} | "
                "需与 Swagger / Apifox 契约核对；待确认请求字段、响应字段、错误码、"
                "权限、风控和幂等规则 |"
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
) -> list[str]:
    target = endpoints[0][0] if endpoints else "接口候选-001"
    pending = (
        "待确认错误码、业务 code、鉴权方式和幂等策略"
        if has_api_doc
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
        for index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, dict):
                continue
            method = str(candidate.get("method") or "GET").upper()
            path = str(candidate.get("path") or "/")
            endpoints.append((f"API-DISC-{index:03d}", method, path, DISCOVERY_SOURCE_LABEL))
        if endpoints:
            return endpoints
    return []


def render_api_test_draft_skeleton(state: QAWorkflowState, repo_root: Path) -> str:
    api_doc = _api_doc_content(state)
    has_api_doc = _has_meaningful_api_doc(api_doc)
    endpoints = _extract_endpoints(api_doc) if has_api_doc else []
    from_discovery = False
    if not has_api_doc:
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
            if not has_api_doc
            else ""
        )
    )
    endpoint_comment = (
        'BASE_URL = os.getenv("AGENTIC_QA_BASE_URL")  # 待确认测试环境域名'
        if has_api_doc or from_discovery
        else 'BASE_URL = os.getenv("AGENTIC_QA_BASE_URL")  # 待补充接口文档后再配置'
    )
    endpoint_method = endpoints[0][1] if endpoints else "POST"
    endpoint_path = endpoints[0][2] if endpoints else "/待确认-url"
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
{chr(10).join(_endpoint_rows(endpoints, has_api_doc=has_api_doc, from_discovery=from_discovery))}

## 2. 接口测试点矩阵

| 接口 | 场景 | 测试类型 | 优先级 | 请求数据 | 断言点 | 前置条件 | 待确认项 |
|---|---|---|---|---|---|---|---|
{chr(10).join(_matrix_rows(endpoints, has_api_doc=has_api_doc, from_discovery=from_discovery))}

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
    state.record_node("api_test_generation_node")
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


def api_test_quality_check_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    if state.task_type != TASK_API_TEST_DRAFT:
        return state
    state.record_node("api_test_quality_check_node")
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
    if not _has_meaningful_api_doc(api_doc) and "待补充接口文档" not in artifact:
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

    prd_path = resolve_prd_path(repo_root, state.prd_path)
    output_path = state.output_paths.get("api_test_draft")
    if not output_path:
        state.quality_errors.append("缺少接口测试草稿输出路径。")
    elif not (repo_root / Path(output_path)).resolve().is_relative_to(prd_path.resolve()):
        state.quality_errors.append("接口测试草稿输出路径必须位于目标 PRD 工作区内。")
    expected_suffix = "/runs/" + (state.run_id or "runtime") + "/artifact-preview.md"
    if output_path and not Path(output_path).as_posix().endswith(expected_suffix):
        state.quality_errors.append(
            "接口测试草稿输出路径不符合约定: runs/<run_id>/artifact-preview.md"
        )
    return state
