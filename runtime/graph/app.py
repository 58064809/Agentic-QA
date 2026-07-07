from __future__ import annotations

from pathlib import Path

from runtime.schemas.runtime_result import RuntimeResult


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


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
    from runtime.graph.mvp_graph import run_requirement_analysis_workflow as run_fn

    return run_fn(
        user_input=user_input,
        prd_path=Path(prd_path),
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
    from runtime.graph.mvp_graph import run_mvp_testcase_generation_workflow as run_fn

    return run_fn(
        user_input=user_input,
        prd_path=Path(prd_path),
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
    from runtime.graph.mvp_graph import run_mvp_analysis_and_testcases_workflow as run_fn

    return run_fn(
        user_input=user_input,
        prd_path=Path(prd_path),
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
    from runtime.graph.mvp_graph import run_api_test_draft_workflow as run_fn

    return run_fn(
        user_input=user_input,
        prd_path=Path(prd_path),
        repo_root=repo_root,
        approve_write=approve_write,
        debug_approve_preview_write=debug_approve_preview_write,
        record_run=record_run,
        use_llm=use_llm,
    )


def run_rag_automation_case_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    debug_approve_preview_write: bool = False,
    record_run: bool = True,
    use_llm: bool = True,
) -> RuntimeResult:
    from runtime.graph.mvp_graph import run_rag_automation_case_workflow as run_fn

    return run_fn(
        user_input=user_input,
        prd_path=Path(prd_path),
        repo_root=repo_root,
        approve_write=approve_write,
        debug_approve_preview_write=debug_approve_preview_write,
        record_run=record_run,
        use_llm=use_llm,
    )


def run_ui_test_draft_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    debug_approve_preview_write: bool = False,
    record_run: bool = True,
    use_llm: bool = True,
) -> RuntimeResult:
    from runtime.graph.mvp_graph import run_ui_test_draft_workflow as run_fn

    return run_fn(
        user_input=user_input,
        prd_path=Path(prd_path),
        repo_root=repo_root,
        approve_write=approve_write,
        debug_approve_preview_write=debug_approve_preview_write,
        record_run=record_run,
        use_llm=use_llm,
    )


def run_api_discovery_report_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    debug_approve_preview_write: bool = False,
    record_run: bool = True,
    use_llm: bool = False,
) -> RuntimeResult:
    from runtime.graph.mvp_graph import run_api_discovery_report_workflow as run_fn

    return run_fn(
        user_input=user_input,
        prd_path=Path(prd_path),
        repo_root=repo_root,
        approve_write=approve_write,
        debug_approve_preview_write=debug_approve_preview_write,
        record_run=record_run,
        use_llm=use_llm,
    )


def run_qa_report_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    debug_approve_preview_write: bool = False,
    record_run: bool = True,
    use_llm: bool = True,
) -> RuntimeResult:
    from runtime.graph.mvp_graph import run_qa_report_workflow as run_fn

    return run_fn(
        user_input=user_input,
        prd_path=Path(prd_path),
        repo_root=repo_root,
        approve_write=approve_write,
        debug_approve_preview_write=debug_approve_preview_write,
        record_run=record_run,
        use_llm=use_llm,
    )


def resume_recorded_workflow(
    run_id: str,
    *,
    action: str | None = None,
    user_input: str | None = None,
    reviewed_by: str = "user",
    review_notes: str | None = None,
    target_artifact: str | None = None,
    repo_root: Path | None = None,
) -> RuntimeResult:
    from runtime.workflow.runner import resume_workflow_for_run

    return resume_workflow_for_run(
        run_id,
        action=action,
        user_input=user_input,
        reviewed_by=reviewed_by,
        review_notes=review_notes,
        target_artifact=target_artifact,
        repo_root=repo_root,
    )


def promote_artifacts(
    prd_path: Path | str,
    run_id: str,
    *,
    repo_root: Path | None = None,
    task_type: str = "mvp_analysis_testcases",
) -> RuntimeResult:
    root = (repo_root or default_repo_root()).resolve()
    from runtime.graph.mvp_graph import promote_mvp_artifacts

    return promote_mvp_artifacts(
        prd_path,
        run_id,
        repo_root=root,
        task_type=task_type,
    )
