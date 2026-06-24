from __future__ import annotations

import json
from pathlib import Path

from runtime.schemas.runtime_result import RuntimeResult


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_testcase_generation_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    record_run: bool = True,
) -> RuntimeResult:
    try:
        from runtime.graph.langgraph_app import run_langgraph_testcase_generation_workflow
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph 未安装或不可用。请先执行 `pip install -e .` 安装运行时依赖。"
        ) from exc

    return run_langgraph_testcase_generation_workflow(
        user_input=user_input,
        prd_path=Path(prd_path),
        repo_root=repo_root,
        approve_write=approve_write,
        record_run=record_run,
    )


def run_requirement_analysis_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    record_run: bool = True,
    use_llm: bool = True,
) -> RuntimeResult:
    try:
        from runtime.graph.mvp_graph import run_requirement_analysis_workflow as run_mvp
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph 未安装或不可用。请先执行 `pip install -e .` 安装运行时依赖。"
        ) from exc

    return run_mvp(
        user_input=user_input,
        prd_path=Path(prd_path),
        repo_root=repo_root,
        approve_write=approve_write,
        record_run=record_run,
        use_llm=use_llm,
    )


def run_mvp_testcase_generation_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    record_run: bool = True,
    use_llm: bool = True,
) -> RuntimeResult:
    try:
        from runtime.graph.mvp_graph import run_mvp_testcase_generation_workflow as run_mvp
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph 未安装或不可用。请先执行 `pip install -e .` 安装运行时依赖。"
        ) from exc

    return run_mvp(
        user_input=user_input,
        prd_path=Path(prd_path),
        repo_root=repo_root,
        approve_write=approve_write,
        record_run=record_run,
        use_llm=use_llm,
    )


def run_mvp_analysis_and_testcases_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
    record_run: bool = True,
    use_llm: bool = True,
) -> RuntimeResult:
    try:
        from runtime.graph.mvp_graph import run_mvp_analysis_and_testcases_workflow as run_mvp
    except ImportError as exc:
        raise RuntimeError(
            "LangGraph 未安装或不可用。请先执行 `pip install -e .` 安装运行时依赖。"
        ) from exc

    return run_mvp(
        user_input=user_input,
        prd_path=Path(prd_path),
        repo_root=repo_root,
        approve_write=approve_write,
        record_run=record_run,
        use_llm=use_llm,
    )


def _read_recorded_task_type(repo_root: Path, run_id: str) -> str | None:
    state_path = repo_root / ".runtime" / "runs" / run_id / "run-state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"未找到运行记录: {state_path.as_posix()}")
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    result = payload.get("result", {})
    if not isinstance(result, dict):
        return None
    task_type = result.get("task_type")
    return str(task_type) if task_type else None


def resume_recorded_workflow(
    run_id: str,
    *,
    action: str | None = None,
    reviewed_by: str = "user",
    review_notes: str | None = None,
    target_artifact: str | None = None,
    repo_root: Path | None = None,
) -> RuntimeResult:
    root = (repo_root or default_repo_root()).resolve()
    task_type = _read_recorded_task_type(root, run_id)

    if task_type in {"analysis", "testcase_generation", "mvp_analysis_testcases"}:
        from runtime.workflow.runner import resume_workflow_for_run

        return resume_workflow_for_run(
            run_id,
            action=action,
            reviewed_by=reviewed_by,
            review_notes=review_notes,
            target_artifact=target_artifact,
            repo_root=root,
        )

    from runtime.graph.langgraph_app import resume_langgraph_testcase_generation_workflow

    return resume_langgraph_testcase_generation_workflow(
        run_id,
        action=action,
        reviewed_by=reviewed_by,
        review_notes=review_notes,
        target_artifact=target_artifact,
        repo_root=root,
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
