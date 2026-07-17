from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness import Harness, ReviewDecision, ReviewIntent, TaskRequest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic-qa", description="Agentic-QA agent harness")
    parser.add_argument("--repo-root", default=".")
    commands = parser.add_subparsers(dest="command", required=True)

    workspace = commands.add_parser("workspace")
    workspace_commands = workspace.add_subparsers(dest="workspace_command", required=True)
    init = workspace_commands.add_parser("init")
    init.add_argument("id")

    run = commands.add_parser("run")
    run.add_argument("workspace")
    run.add_argument("goal")
    run.add_argument(
        "--artifact",
        action="append",
        dest="artifacts",
        help="Expected artifact; may be repeated (default: testcases)",
    )

    inspect = commands.add_parser("inspect")
    inspect.add_argument("run_id")

    resume = commands.add_parser("resume")
    resume.add_argument("run_id")
    resume.add_argument("decision", choices=[item.value for item in ReviewIntent])
    resume.add_argument("--artifact")
    resume.add_argument("--reason", default="Human review decision")
    resume.add_argument("--revision-request")

    agents = commands.add_parser("agents")
    agents.add_subparsers(dest="agents_command", required=True).add_parser("list")
    tools = commands.add_parser("tools")
    tools.add_subparsers(dest="tools_command", required=True).add_parser("list")

    evaluate = commands.add_parser("eval")
    evaluate.add_subparsers(dest="eval_command", required=True).add_parser("run")
    return parser


def _print(value: object) -> None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")  # type: ignore[union-attr]
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    harness = Harness(Path(args.repo_root))
    try:
        if args.command == "workspace":
            print(harness.init_workspace(args.id))
        elif args.command == "run":
            _print(
                harness.run(
                    TaskRequest(
                        workspace=args.workspace,
                        goal=args.goal,
                        expected_artifacts=args.artifacts or ["testcases"],
                    )
                )
            )
        elif args.command == "inspect":
            _print(harness.inspect(args.run_id))
        elif args.command == "resume":
            _print(
                harness.resume(
                    args.run_id,
                    ReviewDecision(
                        intent=args.decision,
                        target_artifact=args.artifact,
                        reason=args.reason,
                        revision_request=args.revision_request,
                    ),
                )
            )
        elif args.command == "agents":
            _print([item.model_dump(mode="json") for item in harness.agents.list()])
        elif args.command == "tools":
            _print([item.model_dump(mode="json") for item in harness.tools.list()])
        elif args.command == "eval":
            from harness.evals import run_offline_eval

            result = run_offline_eval()
            _print(result)
            return 0 if result["passed"] else 1
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
