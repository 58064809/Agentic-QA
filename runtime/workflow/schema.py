from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EXECUTABLE_NODE_TYPES = frozenset(
    {
        "python",
        "rag",
        "agent",
        "validator",
        "writer",
        "review_gate",
        "subgraph",
        "tool",
    }
)


class FailurePolicy(BaseModel):
    """Node-level failure handling strategy."""

    model_config = ConfigDict(frozen=True)

    on_error: str = (
        "fail_workflow"  # retry, skip, fallback, fail_workflow, wait_for_user, compensate
    )
    max_attempts: int = 1
    retry_backoff_seconds: float = 0.0
    fallback_node: str | None = None
    timeout_seconds: float | None = None

    @field_validator("on_error")
    @classmethod
    def validate_on_error(cls, value: str) -> str:
        allowed = {"retry", "skip", "fallback", "fail_workflow", "wait_for_user", "compensate"}
        normalized = value.strip()
        if normalized not in allowed:
            raise ValueError(
                f"不支持的 failure_policy.on_error: {normalized}; "
                f"支持: {', '.join(sorted(allowed))}"
            )
        return normalized

    @field_validator("max_attempts")
    @classmethod
    def validate_max_attempts(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_attempts 必须 >= 1")
        return value


class NodeSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    handler: str | None = None
    workflow: str | None = None
    failure_policy: FailurePolicy | None = None

    @field_validator("type")
    @classmethod
    def validate_node_type(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in EXECUTABLE_NODE_TYPES:
            supported = ", ".join(sorted(EXECUTABLE_NODE_TYPES))
            raise ValueError(f"unsupported node type: {normalized}; supported: {supported}")
        return normalized

    @model_validator(mode="after")
    def validate_execution_target(self) -> NodeSpec:
        if self.type == "subgraph":
            if not self.workflow:
                raise ValueError(f"subgraph node 缂哄皯 workflow: {self.id}")
            if self.handler:
                raise ValueError(f"subgraph node 涓嶅簲璁剧疆 handler: {self.id}")
            return self
        if not self.handler:
            raise ValueError(f"Workflow node 缂哄皯 handler: {self.id}")
        if self.workflow:
            raise ValueError(f"闈?subgraph node 涓嶅簲璁剧疆 workflow: {self.id}")
        return self


class EdgeSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    condition: str | None = None

    @field_validator("condition")
    @classmethod
    def normalize_condition(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WorkflowSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: int = Field(ge=1)
    input: dict[str, str] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    nodes: list[NodeSpec] = Field(default_factory=list, min_length=1)
    edges: list[EdgeSpec] = Field(default_factory=list, min_length=1)
    source_path: str | None = None

    @model_validator(mode="after")
    def validate_unique_nodes_and_edges(self) -> WorkflowSpec:
        node_ids = [node.id for node in self.nodes]
        duplicate_nodes = sorted({node_id for node_id in node_ids if node_ids.count(node_id) > 1})
        if duplicate_nodes:
            raise ValueError(f"Workflow {self.id} 存在重复 node id: {', '.join(duplicate_nodes)}")

        edge_keys = [(edge.source, edge.target, edge.condition) for edge in self.edges]
        duplicate_edges = sorted(
            {edge_key for edge_key in edge_keys if edge_keys.count(edge_key) > 1}
        )
        if duplicate_edges:
            formatted = ", ".join(
                f"{source}->{target}[{condition or 'fixed'}]"
                for source, target, condition in duplicate_edges
            )
            raise ValueError(f"Workflow {self.id} 存在重复 edge: {formatted}")

        return self
