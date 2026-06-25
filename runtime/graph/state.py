"""Single Pydantic state model replacing the old dataclass + TypedDict dual definition."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from runtime.llm.config import default_llm_metadata


class QAWorkflowState(BaseModel):
    """Unified workflow state used directly with LangGraph StateGraph.

    All fields have defaults so LangGraph treats them as optional (matching
    the old ``total=False`` TypedDict contract). Runtime-only fields such as
    ``__interrupt__`` are allowed via ``extra="allow"``.
    """

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    user_input: str = ""
    prd_path: str = ""
    task_type: str | None = None
    intent: str | None = None
    workflow_files: list[str] = Field(default_factory=list)
    loaded_files: dict[str, str] = Field(default_factory=dict)
    draft_artifact: str | None = None
    draft_artifacts: dict[str, str] = Field(default_factory=dict)
    output_paths: dict[str, str] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    quality_errors: list[str] = Field(default_factory=list)
    review_status: str = "not_started"
    next_action: str | None = None
    output_path: str | None = None
    dry_run: bool = True
    approve_write: bool = False
    debug_approve_preview_write: bool = False
    use_llm: bool = False
    fast_llm: bool = False
    max_llm_calls: int = 0
    llm: dict[str, Any] = Field(default_factory=default_llm_metadata)
    requirement_normalization: dict[str, Any] = Field(
        default_factory=lambda: {
            "performed": False,
            "source_path": None,
            "output_path": None,
            "source_type": None,
            "skipped_reason": None,
        }
    )
    prototype_notes: dict[str, Any] = Field(
        default_factory=lambda: {
            "loaded": False,
            "path": None,
            "requirement_has_images": False,
            "warning": None,
        }
    )
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    executed_nodes: list[str] = Field(default_factory=list)
    wrote_file: bool = False
    orchestration: str = "LangGraph StateGraph"
    run_id: str | None = None
    thread_id: str | None = None
    run_status: str = "not_started"
    human_review: dict[str, Any] = Field(
        default_factory=lambda: {
            "status": "not_started",
            "decision": None,
            "reviewed_by": None,
            "review_notes": None,
            "interrupt": None,
        }
    )
    run_record_dir: str | None = None
    run_summary_json: str | None = None
    run_summary_md: str | None = None
    debug_dir: str | None = None
    debug_artifacts: dict[str, str] = Field(default_factory=dict)
    rag_retrievals: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors and not self.quality_errors

    def record_node(self, name: str) -> None:
        self.executed_nodes.append(name)
