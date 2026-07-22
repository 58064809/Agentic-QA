from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness import (
    CreateWorkspaceCommand,
    ExecutionProfile,
    Harness,
    ResumeRunCommand,
    ReviewDecision,
    ReviewIntent,
    ReviewRunCommand,
    RunRef,
    StartRunCommand,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic-qa", description="Agentic-QA v2 harness")
    parser.add_argument("--repo-root", default=".")
    commands = parser.add_subparsers(dest="command", required=True)

    workspace = commands.add_parser("workspace")
    workspace_commands = workspace.add_subparsers(dest="workspace_command", required=True)
    create = workspace_commands.add_parser("create")
    create.add_argument("workspace_id")
    create.add_argument("--quality-policy", action="append", dest="quality_policies")

    run = commands.add_parser("run")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    start = run_commands.add_parser("start")
    start.add_argument("workspace_id")
    start.add_argument("goal")
    start.add_argument("--artifact", action="append", dest="artifacts")
    start.add_argument("--environment", default="analysis-only")
    start.add_argument("--base-url-env")
    start.add_argument("--allow-http-method", action="append", dest="allowed_http_methods")
    start.add_argument("--allow-ui-mutations", action="store_true")
    start.add_argument("--request-timeout-seconds", type=int, default=10)

    get = run_commands.add_parser("get")
    get.add_argument("workspace_id")
    get.add_argument("run_id")

    resume = run_commands.add_parser("resume")
    resume.add_argument("workspace_id")
    resume.add_argument("run_id")

    review = run_commands.add_parser("review")
    review.add_argument("workspace_id")
    review.add_argument("run_id")
    review.add_argument("decision", choices=[item.value for item in ReviewIntent])
    review.add_argument("--artifact")
    review.add_argument("--reason", required=True)
    review.add_argument("--revision-request")
    review.add_argument("--reviewed-by", required=True)

    evaluate = commands.add_parser("eval")
    evaluate.add_subparsers(dest="eval_command", required=True).add_parser("run")
    return parser


def _print(value: object) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")  # type: ignore[union-attr]
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _execution_profile(args: argparse.Namespace) -> ExecutionProfile:
    profile: dict[str, object] = {
        "environment": args.environment,
        "base_url_env": args.base_url_env,
        "allow_ui_mutations": args.allow_ui_mutations,
        "request_timeout_seconds": args.request_timeout_seconds,
    }
    if args.allowed_http_methods:
        profile["allowed_http_methods"] = args.allowed_http_methods
    return ExecutionProfile.model_validate(profile)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    harness = Harness(Path(args.repo_root))
    try:
        if args.command == "workspace":
            print(
                harness.create_workspace(
                    CreateWorkspaceCommand(
                        workspace_id=args.workspace_id,
                        quality_policies=args.quality_policies or [],
                    )
                )
            )
        elif args.command == "run" and args.run_command == "start":
            _print(
                harness.start_run(
                    StartRunCommand(
                        workspace_id=args.workspace_id,
                        goal=args.goal,
                        expected_artifacts=args.artifacts or ["testcases"],
                        execution_profile=_execution_profile(args),
                    )
                )
            )
        elif args.command == "run" and args.run_command == "get":
            _print(harness.get_run(RunRef(workspace_id=args.workspace_id, run_id=args.run_id)))
        elif args.command == "run" and args.run_command == "resume":
            _print(
                harness.resume_run(
                    ResumeRunCommand(workspace_id=args.workspace_id, run_id=args.run_id)
                )
            )
        elif args.command == "run" and args.run_command == "review":
            _print(
                harness.review_run(
                    ReviewRunCommand(
                        workspace_id=args.workspace_id,
                        run_id=args.run_id,
                        decision=ReviewDecision(
                            intent=args.decision,
                            target_artifact=args.artifact,
                            reason=args.reason,
                            revision_request=args.revision_request,
                            reviewed_by=args.reviewed_by,
                        ),
                    )
                )
            )
        elif args.command == "eval":
            from harness.testing.evals import run_offline_eval

            result = run_offline_eval()
            _print(result)
            return 0 if result["passed"] else 1
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
