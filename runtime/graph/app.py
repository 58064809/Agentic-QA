from __future__ import annotations

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
    use_llm: bool = False,
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
    use_llm: bool = False,
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
    use_llm: bool = False,
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
