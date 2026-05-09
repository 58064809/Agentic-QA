from __future__ import annotations

from dataclasses import dataclass

from runtime.graph.state import QAWorkflowState


@dataclass(frozen=True)
class RuntimeResult:
    success: bool
    user_input: str
    prd_path: str
    intent: str | None
    workflow_files: list[str]
    loaded_files: dict[str, str]
    draft_artifact: str | None
    quality_errors: list[str]
    review_status: str
    output_path: str | None
    dry_run: bool
    approve_write: bool
    errors: list[str]
    warnings: list[str]
    executed_nodes: list[str]
    wrote_file: bool
    orchestration: str
    run_id: str | None
    run_record_dir: str | None
    run_summary_json: str | None
    run_summary_md: str | None

    @classmethod
    def from_state(cls, state: QAWorkflowState) -> RuntimeResult:
        return cls(
            success=state.success,
            user_input=state.user_input,
            prd_path=state.prd_path,
            intent=state.intent,
            workflow_files=list(state.workflow_files),
            loaded_files=dict(state.loaded_files),
            draft_artifact=state.draft_artifact,
            quality_errors=list(state.quality_errors),
            review_status=state.review_status,
            output_path=state.output_path,
            dry_run=state.dry_run,
            approve_write=state.approve_write,
            errors=list(state.errors),
            warnings=list(state.warnings),
            executed_nodes=list(state.executed_nodes),
            wrote_file=state.wrote_file,
            orchestration=state.orchestration,
            run_id=state.run_id,
            run_record_dir=state.run_record_dir,
            run_summary_json=state.run_summary_json,
            run_summary_md=state.run_summary_md,
        )
