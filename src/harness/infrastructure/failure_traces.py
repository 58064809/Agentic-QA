from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import requests

from harness.domain.schemas.local_config import LocalTracesConfig
from harness.domain.schemas.log_evidence import ProviderDiagnostic
from harness.domain.schemas.trace_evidence import (
    NormalizedTraceSpan,
    ProviderTraceSpan,
    TraceEvidenceBundle,
    TraceQueryRequest,
    TraceQueryResult,
)
from harness.domain.security import build_api_request_url, validate_api_response_url

REPARSE_POINT = 0x400
SAFE_TRACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,255}$")


class TraceProvider(Protocol):
    def get_trace(self, request: TraceQueryRequest) -> TraceQueryResult: ...


class LocalTraceProvider:
    def __init__(self, repo_root: Path, config: LocalTracesConfig) -> None:
        if config.local_file is None:
            raise ValueError("local trace provider configuration is missing")
        self._root = (repo_root.resolve() / config.local_file.root).resolve()
        self._config = config.local_file

    def get_trace(self, request: TraceQueryRequest) -> TraceQueryResult:
        if not SAFE_TRACE_ID.fullmatch(request.trace_id):
            return self._failed(request, "TRACE_ID_INVALID", "trace ID is not a safe fixture name")
        path = self._root / f"{request.trace_id}.json"
        if not path.exists():
            return TraceQueryResult(
                status="not_found",
                provider="local-file",
                trace_id=request.trace_id,
                diagnostics=[
                    ProviderDiagnostic(
                        code="TRACE_NOT_FOUND", detail="local trace fixture was not found"
                    )
                ],
            )
        try:
            resolved = path.resolve(strict=True)
            if resolved.parent != self._root or not self._safe_regular_file(path, resolved):
                raise ValueError("local trace fixture is outside the configured root")
            if resolved.stat().st_size > self._config.max_file_bytes:
                raise ValueError("local trace fixture exceeds configured byte limit")
            payload = json.loads(resolved.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("local trace fixture must be a JSON object")
            if payload.get("schema_version") != "agentic-qa.local-trace-fixture.v1":
                raise ValueError("local trace fixture schema is unsupported")
            if payload.get("trace_id") != request.trace_id:
                raise ValueError("local trace fixture identity differs from query")
            raw_spans = payload.get("spans")
            if not isinstance(raw_spans, list) or len(raw_spans) > request.max_spans:
                raise ValueError("local trace fixture span count is invalid")
            spans = [ProviderTraceSpan.model_validate(item) for item in raw_spans]
            if any(span.trace_id != request.trace_id for span in spans):
                raise ValueError("local trace span identity differs from query")
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            return self._failed(
                request, "TRACE_FIXTURE_INVALID", f"trace fixture failed with {type(exc).__name__}"
            )
        return TraceQueryResult(
            status="success",
            provider="local-file",
            trace_id=request.trace_id,
            spans=spans,
        )

    @staticmethod
    def _safe_regular_file(path: Path, resolved: Path) -> bool:
        if path.is_symlink() or resolved.is_symlink():
            return False
        file_stat = os.lstat(path)
        if not stat.S_ISREG(file_stat.st_mode):
            return False
        return not bool(getattr(file_stat, "st_file_attributes", 0) & REPARSE_POINT)

    @staticmethod
    def _failed(request: TraceQueryRequest, code: str, detail: str) -> TraceQueryResult:
        return TraceQueryResult(
            status="failed",
            provider="local-file",
            trace_id=request.trace_id,
            diagnostics=[ProviderDiagnostic(code=code, detail=detail)],
        )


class TempoTraceProvider:
    def __init__(self, config: LocalTracesConfig, *, request_func: Any = requests.get) -> None:
        if config.tempo is None:
            raise ValueError("Tempo provider configuration is missing")
        self._traces = config
        self._config = config.tempo
        self._request = request_func

    def get_trace(self, request: TraceQueryRequest) -> TraceQueryResult:
        if not re.fullmatch(r"[a-fA-F0-9]{16,32}", request.trace_id):
            return self._failed(request, "TEMPO_TRACE_ID_INVALID", "Tempo requires a hex trace ID")
        url = build_api_request_url(
            self._config.base_url, f"/api/v2/traces/{request.trace_id.lower()}"
        )
        try:
            response = self._request(
                url,
                params={
                    "start": str(int(request.started_at.timestamp())),
                    "end": str(int(request.completed_at.timestamp())),
                },
                headers={"Authorization": f"Bearer {self._config.token}"},
                timeout=self._config.timeout_seconds,
                allow_redirects=False,
                stream=True,
            )
            validate_api_response_url(getattr(response, "url", None), requested_url=url)
            status = int(response.status_code)
            if 300 <= status < 400:
                return self._failed(
                    request, "TEMPO_REDIRECT_REJECTED", "Tempo redirect was rejected"
                )
            if status == 404:
                return TraceQueryResult(
                    status="not_found",
                    provider="tempo",
                    trace_id=request.trace_id,
                    diagnostics=[
                        ProviderDiagnostic(code="TRACE_NOT_FOUND", detail="Tempo returned 404")
                    ],
                )
            if status != 200:
                return self._failed(request, "TEMPO_HTTP_ERROR", f"Tempo returned HTTP {status}")
            payload = json.loads(self._bounded_body(response).decode("utf-8"))
            spans = self._normalize(payload, request)
        except (
            requests.RequestException,
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            return self._failed(
                request, "TEMPO_QUERY_FAILED", f"Tempo query failed with {type(exc).__name__}"
            )
        return TraceQueryResult(
            status="success", provider="tempo", trace_id=request.trace_id, spans=spans
        )

    def _bounded_body(self, response: Any) -> bytes:
        limit = self._traces.query.max_response_bytes
        header = response.headers.get("Content-Length") if hasattr(response, "headers") else None
        if header and int(header) > limit:
            raise OSError("Tempo response exceeds configured byte limit")
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=65_536):
            if not chunk:
                continue
            size += len(chunk)
            if size > limit:
                raise OSError("Tempo response exceeds configured byte limit")
            chunks.append(chunk)
        return b"".join(chunks)

    def _normalize(self, payload: Any, request: TraceQueryRequest) -> list[ProviderTraceSpan]:
        trace = payload.get("trace") if isinstance(payload, dict) else None
        resources = trace.get("resourceSpans") if isinstance(trace, dict) else None
        if not isinstance(resources, list):
            raise ValueError("Tempo OTLP resourceSpans are missing")
        spans: list[ProviderTraceSpan] = []
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            service = _otlp_attribute(resource.get("resource"), "service.name") or "unknown"
            scopes = resource.get("scopeSpans")
            if not isinstance(scopes, list):
                continue
            for scope in scopes:
                raw_spans = scope.get("spans") if isinstance(scope, dict) else None
                if not isinstance(raw_spans, list):
                    continue
                for raw in raw_spans:
                    spans.append(self._normalize_span(raw, service, request.trace_id))
                    if len(spans) > request.max_spans:
                        raise ValueError("Tempo trace exceeds configured span limit")
        return spans

    @staticmethod
    def _normalize_span(raw: Any, service: str, expected_trace_id: str) -> ProviderTraceSpan:
        if not isinstance(raw, dict):
            raise ValueError("Tempo span must be an object")
        trace_id = _decode_otlp_id(raw.get("traceId"), 16)
        span_id = _decode_otlp_id(raw.get("spanId"), 8)
        parent = _decode_otlp_id(raw.get("parentSpanId"), 8, optional=True)
        if trace_id != expected_trace_id.lower():
            raise ValueError("Tempo span trace ID differs from query")
        attributes = _otlp_attributes(raw.get("attributes"))
        status_value = raw.get("status")
        code = status_value.get("code") if isinstance(status_value, dict) else None
        status = (
            "error"
            if code in {2, "STATUS_CODE_ERROR"}
            else "ok"
            if code in {1, "STATUS_CODE_OK"}
            else "unset"
        )
        error_message = attributes.get("exception.message") or attributes.get("error.message")
        return ProviderTraceSpan(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent,
            service=service,
            operation=str(raw.get("name") or "unknown"),
            span_kind=_span_kind(raw.get("kind")),
            started_at=_otlp_time(raw.get("startTimeUnixNano")),
            ended_at=_otlp_time(raw.get("endTimeUnixNano"), optional=True),
            status=status,
            error_type=_safe_attr(attributes.get("exception.type") or attributes.get("error.type")),
            error_message_digest=(
                hashlib.sha256(str(error_message).encode()).hexdigest() if error_message else None
            ),
            http_method=_safe_attr(
                attributes.get("http.request.method") or attributes.get("http.method")
            ),
            http_status_code=_safe_int(
                attributes.get("http.response.status_code") or attributes.get("http.status_code")
            ),
            rpc_system=_safe_attr(attributes.get("rpc.system")),
            db_system=_safe_attr(attributes.get("db.system") or attributes.get("db.system.name")),
            peer_service=_safe_attr(
                attributes.get("peer.service") or attributes.get("server.address")
            ),
        )

    @staticmethod
    def _failed(request, code, detail):
        return TraceQueryResult(
            status="failed",
            provider="tempo",
            trace_id=request.trace_id,
            diagnostics=[ProviderDiagnostic(code=code, detail=detail)],
        )


def _otlp_attributes(value: Any) -> dict[str, Any]:
    result = {}
    if not isinstance(value, list):
        return result
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            continue
        wrapper = item.get("value")
        if not isinstance(wrapper, dict):
            continue
        for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if key in wrapper:
                result[item["key"]] = wrapper[key]
                break
    return result


def _otlp_attribute(resource: Any, name: str) -> str | None:
    attributes = resource.get("attributes") if isinstance(resource, dict) else None
    value = _otlp_attributes(attributes).get(name)
    return str(value) if value is not None else None


def _decode_otlp_id(value: Any, size: int, *, optional: bool = False) -> str | None:
    if optional and not value:
        return None
    if not isinstance(value, str):
        raise ValueError("OTLP ID must be base64")
    decoded = base64.b64decode(value, validate=True)
    if len(decoded) != size or not any(decoded):
        raise ValueError("OTLP ID has invalid size")
    return decoded.hex()


def _otlp_time(value: Any, *, optional: bool = False) -> datetime | None:
    if optional and not value:
        return None
    return datetime.fromtimestamp(int(value) / 1_000_000_000, tz=UTC)


def _span_kind(value: Any) -> str:
    names = {
        1: "internal",
        2: "server",
        3: "client",
        4: "producer",
        5: "consumer",
        "SPAN_KIND_INTERNAL": "internal",
        "SPAN_KIND_SERVER": "server",
        "SPAN_KIND_CLIENT": "client",
        "SPAN_KIND_PRODUCER": "producer",
        "SPAN_KIND_CONSUMER": "consumer",
    }
    return names.get(value, "unknown")


def _safe_attr(value: Any) -> str | None:
    return str(value)[:256] if value is not None and str(value).strip() else None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    parsed = int(value)
    return parsed if 100 <= parsed <= 599 else None


def build_trace_evidence(
    *,
    collection_id: str,
    execution_sha: str,
    provider_sha: str,
    query: TraceQueryRequest,
    result: TraceQueryResult,
    created_at,
) -> TraceEvidenceBundle:
    ordered = sorted(result.spans, key=lambda span: (span.started_at, span.span_id))
    spans = []
    for index, span in enumerate(ordered, 1):
        duration_ms = None
        if span.ended_at is not None:
            duration_ms = (span.ended_at - span.started_at).total_seconds() * 1000
        spans.append(
            NormalizedTraceSpan(
                **span.model_dump(),
                evidence_ref=f"TRACE-{index:06d}",
                duration_ms=duration_ms,
            )
        )
    roots = [span.evidence_ref for span in spans if not span.parent_span_id]
    values = {
        "schema_version": "agentic-qa.trace-evidence.v1",
        "collection_id": collection_id,
        "execution_id": query.execution_id,
        "case_id": query.case_id,
        "dataset_id": query.dataset_id,
        "trace_id": query.trace_id,
        "execution_evidence_sha256": execution_sha,
        "provider": result.provider,
        "provider_structure_sha256": provider_sha,
        "query": query,
        "status": result.status,
        "spans": spans,
        "root_span_ref": roots[0] if len(roots) == 1 else None,
        "diagnostics": result.diagnostics,
        "created_at": created_at,
    }
    payload = TraceEvidenceBundle.model_construct(**values, content_sha256="0" * 64).model_dump(
        mode="json", exclude={"content_sha256"}
    )
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return TraceEvidenceBundle.model_validate({**payload, "content_sha256": digest})
