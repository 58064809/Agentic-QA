from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from harness import (
    AgentRequest,
    ArtifactDiffEndpoint,
    ArtifactVariant,
    ArtifactVersionRef,
    CreateWorkspaceCommand,
    ExecutionProfile,
    GetArtifactDiffQuery,
    Harness,
    ResumeRunCommand,
    ReviewDecision,
    ReviewIntent,
    ReviewRunCommand,
    RunRef,
    StartRunCommand,
)
from harness.interfaces.agent_gateway import AgentRequestGateway


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
    review.add_argument(
        "--variant",
        action="append",
        dest="variants",
        help="要批准的版本，格式为 artifact=raw 或 artifact=normalized",
    )

    diff = run_commands.add_parser("diff")
    diff.add_argument("workspace_id")
    diff.add_argument("run_id")
    diff.add_argument("artifact")
    diff.add_argument(
        "--before", required=True, choices=[item.value for item in ArtifactDiffEndpoint]
    )
    diff.add_argument(
        "--after", required=True, choices=[item.value for item in ArtifactDiffEndpoint]
    )

    evaluate = commands.add_parser("eval")
    evaluate.add_subparsers(dest="eval_command", required=True).add_parser("run")

    request = commands.add_parser("request")
    request_commands = request.add_subparsers(dest="request_command", required=True)
    request_run = request_commands.add_parser("run")
    request_run.add_argument("request_file")
    request_run.add_argument(
        "--allow-source-root",
        action="append",
        required=True,
        dest="allowed_source_roots",
    )
    request_commands.add_parser("schema")

    mcp = commands.add_parser("mcp")
    mcp_commands = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_serve = mcp_commands.add_parser("serve")
    mcp_serve.add_argument(
        "--allow-source-root",
        action="append",
        required=True,
        dest="allowed_source_roots",
    )
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


def _review_versions(harness: Harness, args: argparse.Namespace) -> list[ArtifactVersionRef]:
    if args.decision != ReviewIntent.APPROVE.value:
        return []
    snapshot = harness.get_run(RunRef(workspace_id=args.workspace_id, run_id=args.run_id))
    requested: dict[str, ArtifactVariant] = {}
    for value in args.variants or []:
        artifact, separator, variant = value.partition("=")
        if not separator:
            raise ValueError("--variant 必须使用 artifact=raw|normalized 格式")
        requested[artifact] = ArtifactVariant(variant)
    targets = (
        [item.artifact for item in snapshot.candidates]
        if args.artifact == "all" or (not args.artifact and len(snapshot.candidates) == 1)
        else [args.artifact]
    )
    refs: list[ArtifactVersionRef] = []
    for artifact in targets:
        candidate = next(item for item in snapshot.candidates if item.artifact == artifact)
        available = {item.variant: item for item in candidate.versions}
        if ArtifactVariant.NORMALIZED in available and artifact not in requested:
            raise ValueError(f"candidate 存在 normalized 版本，必须显式指定 --variant: {artifact}")
        variant = requested.get(artifact, ArtifactVariant.RAW)
        version = available.get(variant)
        if version is None or not candidate.assessment_key or not candidate.quality_report_sha256:
            raise ValueError(
                f"candidate 版本不可用或缺少质量 provenance: {artifact}/{variant.value}"
            )
        refs.append(
            ArtifactVersionRef(
                artifact=artifact,
                variant=variant,
                content_sha256=version.content_sha256,
                assessment_key=candidate.assessment_key,
                quality_report_sha256=candidate.quality_report_sha256,
            )
        )
    return refs


def _load_agent_request(path: Path) -> AgentRequest:
    if not path.is_file():
        raise FileNotFoundError(f"Agent Request 文件不存在: {path}")
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        payload = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    else:
        raise ValueError("Agent Request 只支持 .json、.yaml 或 .yml")
    return AgentRequest.model_validate(payload)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "request":
            if args.request_command == "schema":
                _print(AgentRequest.model_json_schema())
                return 0
            gateway = AgentRequestGateway(
                Path(args.repo_root),
                allowed_source_roots=[Path(item) for item in args.allowed_source_roots],
            )
            _print(gateway.generate_from_sources(_load_agent_request(Path(args.request_file))))
            return 0
        if args.command == "mcp":
            from harness.interfaces.mcp_server import create_mcp_server

            gateway = AgentRequestGateway(
                Path(args.repo_root),
                allowed_source_roots=[Path(item) for item in args.allowed_source_roots],
            )
            create_mcp_server(gateway).run(transport="stdio")
            return 0

        harness = Harness(Path(args.repo_root))
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
                            versions=_review_versions(harness, args),
                        ),
                    )
                )
            )
        elif args.command == "run" and args.run_command == "diff":
            _print(
                harness.get_artifact_diff(
                    GetArtifactDiffQuery(
                        workspace_id=args.workspace_id,
                        run_id=args.run_id,
                        artifact=args.artifact,
                        before=args.before,
                        after=args.after,
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
