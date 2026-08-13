from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from harness.domain.schemas.log_analysis import LogAnalysis
from harness.domain.schemas.log_evidence import LogEvidenceBundle
from harness.domain.schemas.trace_analysis import (
    RootCauseEvidenceGraph,
    RootCauseGraphEdge,
    RootCauseGraphNode,
    TraceAnalysis,
)
from harness.domain.schemas.trace_evidence import TraceEvidenceBundle


def build_root_cause_graph(
    *,
    collection_id: str,
    execution_id: str,
    case_id: str,
    dataset_id: str | None,
    execution_sha: str,
    logs: LogEvidenceBundle | None,
    log_analysis: LogAnalysis | None,
    log_analysis_sha: str | None,
    traces: TraceEvidenceBundle | None,
    trace_analysis: TraceAnalysis | None,
    trace_analysis_sha: str | None,
) -> RootCauseEvidenceGraph:
    nodes = [RootCauseGraphNode(node_id="EXEC-0001", node_type="EXECUTION")]
    edges: list[RootCauseGraphEdge] = []
    spans_by_id = {}
    if traces:
        for span in traces.spans:
            spans_by_id[span.span_id] = span
            nodes.append(
                RootCauseGraphNode(
                    node_id=span.evidence_ref,
                    node_type="SPAN",
                    service=span.service,
                )
            )
            edges.append(
                RootCauseGraphEdge(
                    from_ref="EXEC-0001",
                    to_ref=span.evidence_ref,
                    edge_type="EXECUTION_CONTAINS_SPAN",
                )
            )
        for span in traces.spans:
            if span.parent_span_id in spans_by_id:
                edges.append(
                    RootCauseGraphEdge(
                        from_ref=spans_by_id[span.parent_span_id].evidence_ref,
                        to_ref=span.evidence_ref,
                        edge_type="SPAN_PARENT_OF",
                    )
                )
    if trace_analysis:
        chain = trace_analysis.propagation_chain
        for child, parent in zip(chain, chain[1:], strict=False):
            edges.append(
                RootCauseGraphEdge(
                    from_ref=child,
                    to_ref=parent,
                    edge_type="ERROR_PROPAGATES_TO",
                )
            )
    entries = {entry.entry_id: entry for entry in logs.entries} if logs else {}
    if log_analysis:
        for signal in log_analysis.signals:
            nodes.append(
                RootCauseGraphNode(
                    node_id=signal.signal_id,
                    node_type="LOG_SIGNAL",
                    service=signal.service,
                    category=signal.category,
                )
            )
            if not traces:
                continue
            for span in traces.spans:
                level = _correlation_level(span, signal, entries, logs)
                if level:
                    edges.append(
                        RootCauseGraphEdge(
                            from_ref=span.evidence_ref,
                            to_ref=signal.signal_id,
                            edge_type="SPAN_CORROBORATED_BY_LOG",
                            correlation_level=level,
                        )
                    )
    nodes = sorted(nodes, key=lambda node: (node.node_type, node.node_id))
    edges = sorted(
        edges,
        key=lambda edge: (
            edge.edge_type,
            edge.from_ref,
            edge.to_ref,
            edge.correlation_level or "",
        ),
    )
    values = {
        "collection_id": collection_id,
        "execution_id": execution_id,
        "case_id": case_id,
        "dataset_id": dataset_id,
        "execution_evidence_sha256": execution_sha,
        "log_analysis_sha256": log_analysis_sha,
        "trace_analysis_sha256": trace_analysis_sha,
        "nodes": nodes,
        "edges": edges,
    }
    payload = RootCauseEvidenceGraph.model_construct(**values, content_sha256="0" * 64).model_dump(
        mode="json", exclude={"content_sha256"}
    )
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return RootCauseEvidenceGraph.model_validate({**payload, "content_sha256": digest})


def _correlation_level(span, signal, entries, logs):
    samples = [entries[ref] for ref in signal.sample_refs if ref in entries]
    if any(entry.trace_id == span.trace_id and entry.span_id == span.span_id for entry in samples):
        return "strong"
    if any(
        entry.trace_id == span.trace_id
        and entry.service == span.service
        and entry.timestamp is not None
        and span.started_at - timedelta(seconds=2)
        <= entry.timestamp
        <= (span.ended_at or span.started_at) + timedelta(seconds=2)
        for entry in samples
    ):
        return "medium"
    request_id = logs.query.request_id if logs else None
    if request_id and any(
        entry.request_id == request_id
        and entry.service == span.service
        and entry.timestamp is not None
        and span.started_at - timedelta(seconds=2)
        <= entry.timestamp
        <= (span.ended_at or span.started_at) + timedelta(seconds=2)
        for entry in samples
    ):
        return "possible"
    return None
