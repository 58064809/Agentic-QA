"""CLI: promote/resume 命令处理。"""

from __future__ import annotations

from pathlib import Path

from runtime.cli.parser import (
    _artifact_keys_from_recorded_run,
    _artifact_keys_from_text,
    _clarify_multi_artifact_message,
    _extract_run_id,
    _latest_run_id_for_prd,
    _read_latest_run_id,
    _task_type_from_artifact_keys,
)
from runtime.graph.app import promote_artifacts, resume_recorded_workflow
from runtime.review import ReviewDecision, ReviewIntent, process_review_gate
from runtime.schemas.runtime_result import RuntimeResult
from runtime.workspace import PRDWorkspace


def _approve_reviews_via_gate_for_promotion(
    repo_root: Path,
    prd_rel: str,
    run_id: str,
    artifact_keys: list[str],
    *,
    source_message: str,
    natural_language: bool,
) -> list[str]:
    if natural_language:
        gate_result = process_review_gate(
            repo_root=repo_root,
            prd_path=prd_rel,
            run_id=run_id,
            user_input=source_message,
            artifact_keys=artifact_keys,
        )
        if not gate_result.approved_for_promote:
            details = "; ".join(gate_result.errors) or gate_result.decision.reason
            raise ValueError(f"Review Gate 未批准发布: {details}")
        return gate_result.target_artifacts

    approved_keys: list[str] = []
    for key in artifact_keys:
        gate_result = process_review_gate(
            repo_root=repo_root,
            prd_path=prd_rel,
            run_id=run_id,
            user_input=source_message,
            artifact_keys=[key],
            decision=ReviewDecision(
                intent=ReviewIntent.APPROVE,
                target_artifact=key,
                confidence=1.0,
                reason="显式 promote 命令触发确定性审核通过",
            ),
        )
        if not gate_result.approved_for_promote:
            details = "; ".join(gate_result.errors) or gate_result.decision.reason
            raise ValueError(f"Review Gate 未批准发布 {key}: {details}")
        approved_keys.extend(gate_result.target_artifacts)
    return approved_keys


def _run_promote(
    repo_root: Path,
    prd_rel: str,
    run_id: str | None,
    artifact_keys: list[str],
    *,
    source_message: str,
    natural_language: bool = False,
) -> RuntimeResult:
    workspace = PRDWorkspace(repo_root / prd_rel)
    selected_run_id = run_id or _read_latest_run_id(workspace)
    if not selected_run_id:
        raise ValueError(f"未找到 latest run_id: {workspace.runs_dir / 'latest.yml'}")
    approved_keys = _approve_reviews_via_gate_for_promotion(
        repo_root,
        prd_rel,
        selected_run_id,
        artifact_keys,
        source_message=source_message,
        natural_language=natural_language,
    )
    return promote_artifacts(
        prd_rel,
        selected_run_id,
        repo_root=repo_root,
        task_type=_task_type_from_artifact_keys(approved_keys),
    )


def _run_natural_promote_request(
    user_input: str,
    repo_root: Path,
    fallback_prd: str | None = None,
) -> tuple[str, RuntimeResult]:
    """Handle a natural-language promote request like '测试用例通过，发布正式产物'."""

    prd_rel = _extract_prd_from_natural(user_input, repo_root, fallback_prd)
    run_id = _find_run_for_promote(repo_root, prd_rel)
    artifact_keys = _resolve_artifact_keys(repo_root, run_id, user_input)
    result = _run_promote(
        repo_root,
        prd_rel,
        run_id,
        artifact_keys,
        source_message=user_input,
        natural_language=True,
    )
    return prd_rel, result


def _extract_prd_from_natural(
    user_input: str,
    repo_root: Path,
    fallback_prd: str | None = None,
) -> str:
    from runtime.cli.importer import _ensure_prd_workspace
    from runtime.cli.parser import _extract_prd_workspace_path

    prd_path = _extract_prd_workspace_path(user_input) or fallback_prd
    if not prd_path:
        raise ValueError("未识别 PRD 工作区")
    return _ensure_prd_workspace(repo_root, prd_path)


def _find_run_for_promote(repo_root: Path, prd_rel: str) -> str:
    run_id = _latest_run_id_for_prd(repo_root, prd_rel)
    if not run_id:
        raise ValueError(f"未找到 PRD 运行记录: {prd_rel}")
    return run_id


def _resolve_artifact_keys(
    repo_root: Path,
    run_id: str,
    user_input: str,
) -> list[str]:
    from runtime.cli.parser import _artifact_keys_from_text, _publish_all_requested

    explicit = _artifact_keys_from_text(user_input)
    if explicit:
        return explicit
    recorded = _artifact_keys_from_recorded_run(repo_root, run_id)
    if recorded:
        if len(recorded) > 1 and not _publish_all_requested(user_input):
            msg = _clarify_multi_artifact_message(recorded)
            raise ValueError(msg)
        return recorded
    return ["testcases", "requirement_analysis"]


def _print_promote_result(result: RuntimeResult) -> None:
    if result.errors:
        print("❌ 发布失败:")
        for error in result.errors:
            print(f"   - {error}")
        return
    print("✅ 已发布正式产物")
    for key, path in result.output_paths.items():
        print(f"   - {key}: {path}")


def _print_resume_result(result: RuntimeResult) -> None:
    if result.errors:
        print("❌ 恢复失败:")
        for error in result.errors:
            print(f"   - {error}")
        if result.review_status == "needs_human_review":
            print("   当前仍在等待人工确认，请明确审核动作或目标产物。")
        return
    print("✅ 已恢复 Review Gate")
    print(f"   - run_id: {result.run_id}")
    print(f"   - review_status: {result.review_status}")
    print(f"   - next_action: {result.next_action or '未设置'}")
    if result.review_status == "approved":
        print("   - 下一步: 可执行 promote 发布正式产物")
    elif result.review_status == "needs_human_review":
        print("   - 下一步: 仍需明确人工确认")
    elif result.review_status == "needs_changes":
        print("   - 下一步: 进入修订流程")
    elif result.review_status == "rejected":
        print("   - 下一步: 当前候选产物已拒绝")


def _run_resume_command(args: list[str], repo_root: Path) -> int:
    if not args or args[0] in {"help", "--help", "-h"}:
        print('用法: agentic-qa resume <run_id> "测试用例通过，发布正式产物"')
        return 0
    run_id = args[0]
    message = " ".join(args[1:]).strip()
    if not message:
        print("❌ 缺少自然语言审核意见")
        return 1
    try:
        result = resume_recorded_workflow(
            run_id,
            user_input=message,
            reviewed_by="cli",
            repo_root=repo_root,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"❌ {exc}")
        return 1
    _print_resume_result(result)
    return 0 if result.success else 1


def _run_promote_command(args: list[str], repo_root: Path) -> int:
    if not args or args[0] in {"help", "--help", "-h"}:
        print(
            "用法: agentic-qa promote prd/<requirement> [run_id] [testcases|requirement_analysis]"
        )
        return 0
    from runtime.cli.importer import _ensure_prd_workspace

    prd_rel = _ensure_prd_workspace(repo_root, args[0])
    rest = " ".join(args[1:])
    run_id = _extract_run_id(rest)
    artifact_keys = _artifact_keys_from_text(rest)
    try:
        result = _run_promote(
            repo_root,
            prd_rel,
            run_id,
            artifact_keys,
            source_message="agentic-qa promote " + " ".join(args),
            natural_language=False,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"❌ {exc}")
        return 1
    _print_promote_result(result)
    return 0 if result.success else 1


def _run_workflow(
    *,
    user_input: str,
    prd_path: str,
    intent: str,
    repo_root: Path,
    session: object | None = None,
    debug: bool = False,
) -> RuntimeResult:
    """Execute workflow based on intent.  Called from main loop."""
    from runtime.config import load_app_config

    app_config = load_app_config(repo_root)
    llm_enabled = app_config.workflow.use_llm and not debug
    requirement_analysis_use_llm = llm_enabled and app_config.workflow.use_llm_for(
        "requirement_analysis"
    )
    testcase_generation_use_llm = llm_enabled and app_config.workflow.use_llm_for(
        "testcase_generation"
    )
    mvp_use_llm = llm_enabled and app_config.workflow.use_llm_for("mvp_analysis_testcases")

    approve_write = (
        app_config.workflow.get("approve_write", False)
        if hasattr(app_config.workflow, "get")
        else False
    )
    # Handle potential debug_approve_preview_write
    if session is not None:
        from runtime.session import Session as _S

        if isinstance(session, _S):
            approve_write = approve_write or session.debug_approve_preview_write

    if intent == "requirement_analysis":
        from runtime.graph.app import run_requirement_analysis_workflow

        return run_requirement_analysis_workflow(
            user_input=user_input,
            prd_path=Path(prd_path),
            repo_root=repo_root,
            approve_write=approve_write,
            record_run=True,
            use_llm=requirement_analysis_use_llm,
        )
    elif intent == "testcase_generation":
        from runtime.graph.app import run_mvp_testcase_generation_workflow

        return run_mvp_testcase_generation_workflow(
            user_input=user_input,
            prd_path=Path(prd_path),
            repo_root=repo_root,
            approve_write=approve_write,
            record_run=True,
            use_llm=testcase_generation_use_llm,
        )
    else:
        from runtime.graph.app import run_mvp_analysis_and_testcases_workflow

        return run_mvp_analysis_and_testcases_workflow(
            user_input=user_input,
            prd_path=Path(prd_path),
            repo_root=repo_root,
            approve_write=approve_write,
            record_run=True,
            use_llm=mvp_use_llm,
        )
