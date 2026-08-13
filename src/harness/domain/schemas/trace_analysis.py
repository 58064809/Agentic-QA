from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from harness.domain.models import StrictModel


class DependencyFailure(StrictModel):
    caller_service: str
    dependency: str
    span_ref: str = Field(pattern=r"^TRACE-[0-9]{6}$")
    failure_type: Literal["timeout", "http_5xx", "rpc", "database", "dependency_error"]


class TracePrimaryFailure(StrictModel):
    span_ref: str = Field(pattern=r"^TRACE-[0-9]{6}$")
    service: str
    dependency: str | None = None
    failure_type: Literal[
        "timeout", "http_5xx", "rpc", "database", "dependency_error", "span_error"
    ]


class TraceAnalysis(StrictModel):
    schema_version: Literal["agentic-qa.trace-analysis.v1"] = "agentic-qa.trace-analysis.v1"
    collection_id: str
    execution_id: str
    case_id: str
    dataset_id: str | None = None
    trace_evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    analysis_status: Literal["success", "empty", "degraded", "failed"]
    root_span_ref: str | None = None
    first_error_span_ref: str | None = None
    primary_failure: TracePrimaryFailure | None = None
    propagation_chain: list[str] = Field(default_factory=list)
    critical_path: list[str] = Field(default_factory=list)
    critical_path_duration_ms: float | None = Field(default=None, ge=0)
    slowest_span_ref: str | None = None
    dependency_failures: list[DependencyFailure] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_hash(self) -> TraceAnalysis:
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("trace analysis content hash does not match")
        return self


GraphNodeType = Literal["EXECUTION", "SPAN", "LOG_SIGNAL"]
GraphEdgeType = Literal[
    "EXECUTION_CONTAINS_SPAN",
    "SPAN_PARENT_OF",
    "SPAN_CORROBORATED_BY_LOG",
    "ERROR_PROPAGATES_TO",
]


class RootCauseGraphNode(StrictModel):
    node_id: str
    node_type: GraphNodeType
    service: str | None = None
    category: str | None = None


class RootCauseGraphEdge(StrictModel):
    from_ref: str
    to_ref: str
    edge_type: GraphEdgeType
    correlation_level: Literal["strong", "medium", "possible"] | None = None


class RootCauseEvidenceGraph(StrictModel):
    schema_version: Literal["agentic-qa.root-cause-evidence-graph.v1"] = (
        "agentic-qa.root-cause-evidence-graph.v1"
    )
    collection_id: str
    execution_id: str
    case_id: str
    dataset_id: str | None = None
    execution_evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    log_analysis_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    trace_analysis_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    nodes: list[RootCauseGraphNode]
    edges: list[RootCauseGraphEdge]
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_graph(self) -> RootCauseEvidenceGraph:
        node_ids = {node.node_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("root cause graph node IDs must be unique")
        if any(edge.from_ref not in node_ids or edge.to_ref not in node_ids for edge in self.edges):
            raise ValueError("root cause graph edge has unresolved endpoint")
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("root cause graph content hash does not match")
        return self
