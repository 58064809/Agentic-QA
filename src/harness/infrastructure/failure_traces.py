from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Protocol

from harness.domain.schemas.local_config import LocalTracesConfig
from harness.domain.schemas.log_evidence import ProviderDiagnostic
from harness.domain.schemas.trace_evidence import (
    NormalizedTraceSpan,
    ProviderTraceSpan,
    TraceEvidenceBundle,
    TraceQueryRequest,
    TraceQueryResult,
)

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
