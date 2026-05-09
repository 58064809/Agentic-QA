from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QAWorkflowState:
    user_input: str
    prd_path: str
    intent: str | None = None
    workflow_files: list[str] = field(default_factory=list)
    loaded_files: dict[str, str] = field(default_factory=dict)
    draft_artifact: str | None = None
    quality_errors: list[str] = field(default_factory=list)
    review_status: str = "not_started"
    output_path: str | None = None
    dry_run: bool = True
    approve_write: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    executed_nodes: list[str] = field(default_factory=list)
    wrote_file: bool = False

    @property
    def success(self) -> bool:
        return not self.errors and not self.quality_errors

    def record_node(self, name: str) -> None:
        self.executed_nodes.append(name)
