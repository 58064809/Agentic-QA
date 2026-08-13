from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from harness.domain.schemas.trace_analysis import (
    DependencyFailure,
    TraceAnalysis,
    TracePrimaryFailure,
)
from harness.domain.schemas.trace_evidence import NormalizedTraceSpan, TraceEvidenceBundle


def derive_trace_analysis(bundle: TraceEvidenceBundle, evidence_sha: str) -> TraceAnalysis:
    spans = bundle.spans
    diagnostics: set[str] = set()
    by_id: dict[str, NormalizedTraceSpan] = {}
    duplicates: set[str] = set()
    for span in spans:
        if span.span_id in by_id:
            duplicates.add(span.span_id)
        else:
            by_id[span.span_id] = span
    if duplicates:
        diagnostics.add("duplicate_span_id")
    children: dict[str, list[NormalizedTraceSpan]] = defaultdict(list)
    roots: list[NormalizedTraceSpan] = []
    orphans: set[str] = set()
    for span in spans:
        if not span.parent_span_id:
            roots.append(span)
        elif span.parent_span_id not in by_id:
            diagnostics.add("missing_parent")
            diagnostics.add("orphan_span")
            orphans.add(span.span_id)
        else:
            children[span.parent_span_id].append(span)
    if not roots:
        diagnostics.add("missing_root")
    elif len(roots) > 1:
        diagnostics.add("multiple_roots")
    cycle = _has_cycle(by_id, children)
    if cycle:
        diagnostics.add("cycle")
    invalid_graph = bool(duplicates or cycle or len(roots) != 1)
    errors = sorted((span for span in spans if _is_error(span)), key=_span_order)
    first_error = errors[0].evidence_ref if errors else None
    dependency_failures = sorted(
        (failure for span in spans if (failure := _dependency_failure(span)) is not None),
        key=lambda item: item.span_ref,
    )
    primary = None
    propagation: list[str] = []
    critical: list[str] = []
    critical_duration = None
    root_ref = roots[0].evidence_ref if len(roots) == 1 else None
    if not invalid_graph:
        depths = _depths(roots[0], children)
        eligible = [span for span in errors if span.span_id not in orphans]
        dependency_refs = {item.span_ref for item in dependency_failures}
        preferred = [span for span in eligible if span.evidence_ref in dependency_refs]
        candidates = preferred or eligible
        if candidates:
            selected = sorted(
                candidates,
                key=lambda span: (
                    -depths.get(span.span_id, 0),
                    *_span_order(span),
                ),
            )[0]
            failure = next(
                (item for item in dependency_failures if item.span_ref == selected.evidence_ref),
                None,
            )
            primary = TracePrimaryFailure(
                span_ref=selected.evidence_ref,
                service=selected.service,
                dependency=failure.dependency if failure else None,
                failure_type=failure.failure_type if failure else "span_error",
            )
            propagation = _propagation(selected, by_id)
        critical, critical_duration = _critical_path(roots[0], children)
    slowest = min(
        (span for span in spans if span.duration_ms is not None),
        key=lambda span: (-float(span.duration_ms or 0), span.evidence_ref),
        default=None,
    )
    status = "empty" if not spans else "degraded" if diagnostics else "success"
    values = {
        "schema_version": "agentic-qa.trace-analysis.v1",
        "collection_id": bundle.collection_id,
        "execution_id": bundle.execution_id,
        "case_id": bundle.case_id,
        "dataset_id": bundle.dataset_id,
        "trace_evidence_sha256": evidence_sha,
        "analysis_status": status,
        "root_span_ref": root_ref,
        "first_error_span_ref": first_error,
        "primary_failure": primary,
        "propagation_chain": propagation,
        "critical_path": critical,
        "critical_path_duration_ms": critical_duration,
        "slowest_span_ref": slowest.evidence_ref if slowest else None,
        "dependency_failures": dependency_failures,
        "diagnostics": sorted(diagnostics),
    }
    payload = TraceAnalysis.model_construct(**values, content_sha256="0" * 64).model_dump(
        mode="json", exclude={"content_sha256"}
    )
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return TraceAnalysis.model_validate({**payload, "content_sha256": digest})


def _is_error(span: NormalizedTraceSpan) -> bool:
    return bool(
        span.status == "error"
        or (span.http_status_code is not None and span.http_status_code >= 500)
        or span.error_type
    )


def _dependency_failure(span: NormalizedTraceSpan) -> DependencyFailure | None:
    dependency = span.peer_service or span.db_system or span.rpc_system
    if span.span_kind != "client" or not dependency or not _is_error(span):
        return None
    marker = (span.error_type or "").casefold()
    if "deadline" in marker or "timeout" in marker or span.http_status_code == 504:
        failure_type = "timeout"
    elif span.http_status_code is not None and span.http_status_code >= 500:
        failure_type = "http_5xx"
    elif span.db_system:
        failure_type = "database"
    elif span.rpc_system:
        failure_type = "rpc"
    else:
        failure_type = "dependency_error"
    return DependencyFailure(
        caller_service=span.service,
        dependency=dependency,
        span_ref=span.evidence_ref,
        failure_type=failure_type,
    )


def _span_order(span: NormalizedTraceSpan) -> tuple:
    return span.started_at, span.span_id


def _has_cycle(by_id, children) -> bool:
    state: dict[str, int] = {}

    def visit(span_id: str) -> bool:
        if state.get(span_id) == 1:
            return True
        if state.get(span_id) == 2:
            return False
        state[span_id] = 1
        if any(visit(child.span_id) for child in children.get(span_id, [])):
            return True
        state[span_id] = 2
        return False

    return any(visit(span_id) for span_id in by_id if state.get(span_id) is None)


def _depths(root, children) -> dict[str, int]:
    values = {root.span_id: 0}
    queue = [root]
    while queue:
        parent = queue.pop(0)
        for child in sorted(children.get(parent.span_id, []), key=_span_order):
            values[child.span_id] = values[parent.span_id] + 1
            queue.append(child)
    return values


def _propagation(span, by_id) -> list[str]:
    result = [span.evidence_ref]
    current = span
    seen = {span.span_id}
    while current.parent_span_id and current.parent_span_id in by_id:
        parent = by_id[current.parent_span_id]
        if parent.span_id in seen or not _is_error(parent):
            break
        seen.add(parent.span_id)
        result.append(parent.evidence_ref)
        current = parent
    return result


def _critical_path(root, children) -> tuple[list[str], float]:
    def walk(span) -> tuple[list[str], float]:
        own = float(span.duration_ms or 0)
        child_paths = [walk(child) for child in children.get(span.span_id, [])]
        if not child_paths:
            return [span.evidence_ref], own
        path, duration = min(child_paths, key=lambda item: (-item[1], item[0]))
        return [span.evidence_ref, *path], own + duration

    return walk(root)
