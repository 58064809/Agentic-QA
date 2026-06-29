from __future__ import annotations

from pathlib import Path

from runtime.graph.app import default_repo_root
from runtime.graph.nodes.artifact_promoter import promote_artifacts
from runtime.schemas.runtime_result import RuntimeResult


def promote_mvp_artifacts(
    prd_path: Path | str,
    run_id: str,
    *,
    repo_root: Path | None = None,
    task_type: str = "mvp_analysis_testcases",
) -> RuntimeResult:
    root = (repo_root or default_repo_root()).resolve()
    state = promote_artifacts(
        prd_path,
        run_id,
        repo_root=root,
        task_type=task_type,
    )
    return RuntimeResult.from_state(state)


def run_requirement_analysis_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    debug_approve_preview_write: bool = False,
    record_run: bool = True,
    use_llm: bool = True,
) -> RuntimeResult:
    from runtime.workflow import run_workflow_by_id

    return run_workflow_by_id(
        workflow_id="requirement_analysis",
        user_input=user_input,
        prd_path=prd_path,
        repo_root=repo_root,
        approve_write=approve_write,
        debug_approve_preview_write=debug_approve_preview_write,
        record_run=record_run,
        use_llm=use_llm,
    )


def run_mvp_testcase_generation_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    debug_approve_preview_write: bool = False,
    record_run: bool = True,
    use_llm: bool = True,
) -> RuntimeResult:
    from runtime.workflow import run_workflow_by_id

    return run_workflow_by_id(
        workflow_id="testcase_generation",
        user_input=user_input,
        prd_path=prd_path,
        repo_root=repo_root,
        approve_write=approve_write,
        debug_approve_preview_write=debug_approve_preview_write,
        record_run=record_run,
        use_llm=use_llm,
    )


def run_mvp_analysis_and_testcases_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    debug_approve_preview_write: bool = False,
    record_run: bool = True,
    use_llm: bool = True,
) -> RuntimeResult:
    from runtime.workflow import run_workflow_by_id

    return run_workflow_by_id(
        workflow_id="analysis_and_testcases",
        user_input=user_input,
        prd_path=prd_path,
        repo_root=repo_root,
        approve_write=approve_write,
        debug_approve_preview_write=debug_approve_preview_write,
        record_run=record_run,
        use_llm=use_llm,
    )


def run_api_test_draft_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    debug_approve_preview_write: bool = False,
    record_run: bool = True,
    use_llm: bool = True,
) -> RuntimeResult:
    from runtime.workflow import run_workflow_by_id

    return run_workflow_by_id(
        workflow_id="api_test_draft",
        user_input=user_input,
        prd_path=prd_path,
        repo_root=repo_root,
        approve_write=approve_write,
        debug_approve_preview_write=debug_approve_preview_write,
        record_run=record_run,
        use_llm=use_llm,
    )
