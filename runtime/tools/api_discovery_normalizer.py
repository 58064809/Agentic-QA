from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from runtime.tools.network_sanitizer import sanitize_headers, sanitize_json, schema_summary

STATIC_EXTENSIONS = (
    ".js",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".gif",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
    ".ico",
)
STATIC_RESOURCE_TYPES = {"script", "stylesheet", "image", "font", "media"}


@dataclass(frozen=True)
class NetworkCall:
    order: int
    method: str
    url: str
    path: str
    status: int | None
    resource_type: str
    duration_ms: float | None
    request_headers: dict[str, Any] = field(default_factory=dict)
    response_headers: dict[str, Any] = field(default_factory=dict)
    request_body_schema: Any = None
    response_body_schema: Any = None
    source: str = "playwright-network-capture"

    @property
    def is_business_candidate(self) -> bool:
        return not _is_static(self.url, self.resource_type)


@dataclass(frozen=True)
class ApiCandidate:
    method: str
    path: str
    call_count: int
    status_codes: list[int]
    avg_duration_ms: float | None
    request_schema: Any
    response_schema: Any
    source: str = "playwright-network-capture"


@dataclass(frozen=True)
class ApiDiscoveryResult:
    source_path: str
    calls: list[NetworkCall]
    candidates: list[ApiCandidate]


def load_network_capture(path: Path) -> ApiDiscoveryResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict | list):
        raise ValueError("抓包文件必须是 HAR 对象或 network call 列表")
    raw_calls = _raw_calls(payload)
    calls = [_normalize_call(index, raw) for index, raw in enumerate(raw_calls, start=1)]
    business_calls = [call for call in calls if call.is_business_candidate]
    candidates = _merge_candidates(business_calls)
    return ApiDiscoveryResult(
        source_path=path.as_posix(),
        calls=calls,
        candidates=candidates,
    )


def render_api_discovery_report(result: ApiDiscoveryResult, *, run_id: str | None = None) -> str:
    lines = [
        "---",
        "status: needs_human_review",
        "artifact_type: api_discovery_report",
        "human_review_required: true",
        "generated_by: agentic-qa-runtime",
        "---",
        "",
        "# 接口发现报告",
        "",
        "## 1. 采集来源",
        "",
        f"- run_id：{run_id or '未记录'}",
        "- 页面入口：来自离线 network-capture 文件，待确认具体页面。",
        "- 执行环境：离线解析，本次未启动浏览器、未访问真实环境。",
        f"- 来源文件：`{result.source_path}`",
        "- 来源类型：Playwright network capture / HAR。",
        "",
        "## 2. 接口调用链",
        "",
        "| 顺序 | Method | Path | Status | 类型 | 耗时 | 候选 |",
        "|---|---|---|---|---|---|---|",
    ]
    for call in result.calls:
        lines.append(
            f"| {call.order} | {call.method} | {call.path} | "
            f"{call.status or '未知'} | {call.resource_type or 'unknown'} | "
            f"{call.duration_ms or '未知'} | "
            f"{'是' if call.is_business_candidate else '否'} |"
        )
    lines.extend(
        [
            "",
            "## 3. 业务接口候选清单",
            "",
            "| 接口 | 调用次数 | 来源 | 待确认项 |",
            "|---|---|---|---|",
        ]
    )
    if not result.candidates:
        lines.append(
            "| 未发现业务接口候选 | 0 | playwright-network-capture | " "未发现业务接口候选 |"
        )
    for candidate in result.candidates:
        lines.append(
            f"| {candidate.method} {candidate.path} | {candidate.call_count} | "
            "playwright-network-capture | 需与 Swagger / Apifox 契约核对 |"
        )
    lines.extend(["", "## 4. 请求/响应结构摘要", ""])
    if not result.candidates:
        lines.append("- 未发现业务接口候选。")
    for candidate in result.candidates:
        lines.extend(
            [
                f"### {candidate.method} {candidate.path}",
                "",
                "- Query 参数：从 URL query 推断，是否必填待确认。",
                "- Request Body Schema 摘要："
                f"`{json.dumps(candidate.request_schema, ensure_ascii=False)}`",
                "- Response Body Schema 摘要："
                f"`{json.dumps(candidate.response_schema, ensure_ascii=False)}`",
                "- Status Codes："
                f"{', '.join(str(code) for code in candidate.status_codes) or '未知'}",
                "",
            ]
        )
    lines.extend(
        [
            "## 5. 与 Swagger / Apifox 契约的关系",
            "",
            "- 抓包结果只代表运行时流量，不是完整接口契约。",
            "- 需与 Swagger / Apifox 核对 URL、Method、字段必填、枚举和错误码。",
            "- 不能据此确认所有字段必填、权限规则或异常响应。",
            "",
            "## 6. 可转入 api-test-draft 的测试建议",
            "",
            "- 主流程成功：基于抓包中的 2xx 接口候选设计正向断言。",
            "- 参数缺失：字段是否必填需与接口契约核对。",
            "- 类型错误：根据 schema 摘要生成待确认测试点。",
            "- 鉴权失败：补充未登录、无效 token、权限不足场景。",
            "- 幂等/重复提交：对提交类接口补充重复点击和接口重放场景。",
            "- 异常响应：补充 4xx/5xx 和业务 code 异常断言。",
            "",
            "## 7. 脱敏说明",
            "",
            "- 已脱敏字段：Authorization、Cookie、Set-Cookie、token、access_token。",
            "- 已脱敏字段：refresh_token、session、JSESSIONID。",
            "- 已脱敏 PII：手机号、身份证、银行卡等。",
            "- 未保存字段：完整敏感 response body；报告只保留 schema 摘要。",
            "- 风险提示：如发现未脱敏字段，必须删除候选产物并修正脱敏规则后重新生成。",
            "",
            "## 8. 待确认问题",
            "",
            "- [ ] 抓包来源页面、账号角色和测试环境是否准确。",
            "- [ ] 业务接口候选是否与 Swagger / Apifox 契约一致。",
            "- [ ] 请求字段是否必填、错误码和异常响应是否完整。",
            "- [ ] 权限、风控、幂等和数据一致性规则是否需要补充。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _raw_calls(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    log = payload.get("log")
    if isinstance(log, dict) and isinstance(log.get("entries"), list):
        return [entry for entry in log["entries"] if isinstance(entry, dict)]
    calls = payload.get("calls") or payload.get("entries")
    if isinstance(calls, list):
        return [item for item in calls if isinstance(item, dict)]
    raise ValueError("抓包文件缺少 HAR log.entries 或 calls")


def _normalize_call(order: int, raw: dict[str, Any]) -> NetworkCall:
    request = raw.get("request") if isinstance(raw.get("request"), dict) else raw
    response = raw.get("response") if isinstance(raw.get("response"), dict) else {}
    url = str(request.get("url") or raw.get("url") or "")
    method = str(request.get("method") or raw.get("method") or "GET").upper()
    resource_type = str(
        raw.get("resource_type") or raw.get("resourceType") or raw.get("_resourceType") or ""
    )
    status = response.get("status") or raw.get("status")
    duration = raw.get("time") or raw.get("duration_ms") or raw.get("duration")
    request_body = _json_like(
        request.get("postData") or raw.get("post_data") or raw.get("request_body")
    )
    response_body = _json_like(response.get("content") or raw.get("response_body"))
    return NetworkCall(
        order=order,
        method=method,
        url=url,
        path=_path_from_url(url),
        status=(
            int(status) if isinstance(status, int | float | str) and str(status).isdigit() else None
        ),
        resource_type=resource_type,
        duration_ms=float(duration) if isinstance(duration, int | float) else None,
        request_headers=sanitize_headers(_headers_mapping(request.get("headers"))),
        response_headers=sanitize_headers(_headers_mapping(response.get("headers"))),
        request_body_schema=schema_summary(request_body) if request_body is not None else {},
        response_body_schema=schema_summary(response_body) if response_body is not None else {},
    )


def _merge_candidates(calls: list[NetworkCall]) -> list[ApiCandidate]:
    grouped: dict[tuple[str, str], list[NetworkCall]] = {}
    for call in calls:
        grouped.setdefault((call.method, call.path), []).append(call)
    candidates: list[ApiCandidate] = []
    for (method, path), items in sorted(grouped.items()):
        durations = [item.duration_ms for item in items if item.duration_ms is not None]
        status_codes = sorted({item.status for item in items if item.status is not None})
        candidates.append(
            ApiCandidate(
                method=method,
                path=path,
                call_count=len(items),
                status_codes=status_codes,
                avg_duration_ms=round(sum(durations) / len(durations), 2) if durations else None,
                request_schema=items[0].request_body_schema,
                response_schema=items[0].response_body_schema,
            )
        )
    return candidates


def _headers_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {
            str(item.get("name")): item.get("value")
            for item in value
            if isinstance(item, dict) and item.get("name")
        }
    return {}


def _json_like(value: Any) -> Any:
    if isinstance(value, dict) and "text" in value:
        value = value.get("text")
    if isinstance(value, dict | list):
        return sanitize_json(value)
    if isinstance(value, str) and value.strip():
        try:
            return sanitize_json(json.loads(value))
        except json.JSONDecodeError:
            return sanitize_json(value)
    return None


def _path_from_url(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path or url
    return path or "/"


def _is_static(url: str, resource_type: str) -> bool:
    path = _path_from_url(url).lower()
    return resource_type.lower() in STATIC_RESOURCE_TYPES or path.endswith(STATIC_EXTENSIONS)
