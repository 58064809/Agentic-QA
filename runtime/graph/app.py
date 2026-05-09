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
    )
