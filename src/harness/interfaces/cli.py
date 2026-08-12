from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from harness import (
    AgentRequest,
    AnalyzeFailureCommand,
    ApiProjectCheckCommand,
    ApiScenarioPrepareCommand,
    ArtifactDiffEndpoint,
    ArtifactVariant,
    ArtifactVersionRef,
    CollectFailureLogsCommand,
    CreateWorkspaceCommand,
    ExecuteApiCasesCommand,
    ExecutionProfile,
    ExportApiPytestCommand,
    GenerateApiAllureReportCommand,
    GetArtifactDiffQuery,
    Harness,
    PrepareFailureReportCommand,
    ResumeApiCleanupCommand,
    ResumeRunCommand,
    ReviewDecision,
    ReviewIntent,
    ReviewRunCommand,
    RunApiScenarioCommand,
    RunRef,
    StartRunCommand,
)
from harness.infrastructure.local_config import FilesystemLocalConfigLoader
from harness.interfaces.agent_gateway import AgentRequestGateway


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic-qa", description="Agentic-QA v2 harness")
    parser.add_argument("--repo-root", default=".")
    commands = parser.add_subparsers(dest="command", required=True)

    config = commands.add_parser("config")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("init")
    config_commands.add_parser("doctor")
    runtime_key = config_commands.add_parser("runtime-key")
    runtime_key_commands = runtime_key.add_subparsers(dest="runtime_key_command", required=True)
    runtime_key_commands.add_parser("init")
    secrets = config_commands.add_parser("secrets")
    secret_commands = secrets.add_subparsers(dest="secret_command", required=True)
    secret_commands.add_parser("migrate")

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
    eval_commands = evaluate.add_subparsers(dest="eval_command", required=True)
    eval_commands.add_parser("run")
    eval_live = eval_commands.add_parser("live")
    eval_live.add_argument("--case", dest="case_name")
    eval_live.add_argument("--output-dir")

    request = commands.add_parser("request")
    request_commands = request.add_subparsers(dest="request_command", required=True)
    request_run = request_commands.add_parser("run")
    request_run.add_argument("request_file")
    request_run.add_argument(
        "--allow-source-root",
        action="append",
        dest="allowed_source_roots",
        help="追加允许导入的绝对路径；项目内 local-sources/requirements 始终可用",
    )
    request_commands.add_parser("schema")

    mcp = commands.add_parser("mcp")
    mcp_commands = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_serve = mcp_commands.add_parser("serve")
    mcp_serve.add_argument(
        "--allow-source-root",
        action="append",
        dest="allowed_source_roots",
        help="追加允许导入的绝对路径；项目内 local-sources/requirements 始终可用",
    )
    api = commands.add_parser("api")
    api_commands = api.add_subparsers(dest="api_command", required=True)
    api_doctor = api_commands.add_parser("doctor")
    api_doctor.add_argument("source_directory")
    api_doctor.add_argument("--environment", required=True)
    api_prepare = api_commands.add_parser("prepare")
    api_prepare.add_argument("source_directory")
    api_prepare.add_argument(
        "--goal",
        default="Assemble reviewed manual API test cases into contract-bounded API scenarios",
    )
    api_prepare.add_argument("--workspace-id")
    api_prepare.add_argument("--request-id")
    api_prepare.add_argument("--environment", required=True)
    api_prepare.add_argument("--quality-policy", action="append", dest="quality_policies")
    api_run = api_commands.add_parser("run")
    api_run.add_argument("workspace_id")
    api_run.add_argument("execution_id")
    api_run.add_argument("--environment", required=True)
    api_report = api_commands.add_parser("report")
    api_report_commands = api_report.add_subparsers(dest="api_report_command", required=True)
    api_report_allure = api_report_commands.add_parser("allure")
    api_report_allure.add_argument("workspace_id")
    api_report_allure.add_argument("execution_id")
    api_cleanup = api_commands.add_parser("cleanup")
    api_cleanup_commands = api_cleanup.add_subparsers(dest="api_cleanup_command", required=True)
    api_cleanup_resume = api_cleanup_commands.add_parser("resume")
    api_cleanup_resume.add_argument("workspace_id")
    api_cleanup_resume.add_argument("execution_id")
    api_cleanup_resume.add_argument("--environment", required=True)
    api_execute = api_commands.add_parser("execute")
    api_execute.add_argument("workspace_id")
    api_execute.add_argument("run_id")
    api_execute.add_argument("--cases-path", default="published/api_test_draft/current.yml")
    api_execute.add_argument("--environment", required=True)

    api_export = api_commands.add_parser("export-pytest")
    api_export.add_argument("workspace_id")
    api_export.add_argument("--cases-path", default="published/api_test_draft/current.yml")
    api_export.add_argument("--output-path", default="exports/api_test_draft/test_api_cases.py")
    api_export.add_argument("--overwrite", action="store_true")
    failure = commands.add_parser("failure")
    failure_commands = failure.add_subparsers(dest="failure_command", required=True)
    failure_collect = failure_commands.add_parser("collect")
    failure_collect.add_argument("workspace_id")
    failure_collect.add_argument("execution_id")
    failure_collect.add_argument("--case-id")
    failure_analyze = failure_commands.add_parser("analyze")
    failure_analyze.add_argument("workspace_id")
    failure_analyze.add_argument("execution_id")
    failure_analyze.add_argument("--case-id")
    failure_analyze.add_argument("--collection-id")
    failure_report = failure_commands.add_parser("report")
    failure_report.add_argument("workspace_id")
    failure_report.add_argument("execution_id")
    failure_report.add_argument("--case-id")
    failure_report.add_argument("--collection-id")
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
        refs.append(candidate.version_ref(variant))
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


def _load_mapping(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"configuration file does not exist: {path}")
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.casefold() == ".json":
        payload = json.loads(text)
    elif path.suffix.casefold() in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    else:
        raise ValueError("configuration file must be .json, .yaml, or .yml")
    if not isinstance(payload, dict):
        raise ValueError("configuration file must contain an object")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        repo_root = Path(args.repo_root).resolve()
        if args.command == "config":
            loader = FilesystemLocalConfigLoader(repo_root)
            if args.config_command == "init":
                print(loader.init())
                return 0
            if args.config_command == "runtime-key":
                print(loader.init_runtime_key())
                return 0
            if args.config_command == "secrets":
                print(loader.migrate_inline_secrets())
                return 0
            result = loader.check()
            _print(result)
            return 0 if result.ready else 2
        if args.command == "request":
            if args.request_command == "schema":
                _print(AgentRequest.model_json_schema())
                return 0
            gateway = AgentRequestGateway(
                Path(args.repo_root),
                allowed_source_roots=[Path(item) for item in (args.allowed_source_roots or [])],
            )
            _print(gateway.generate_from_sources(_load_agent_request(Path(args.request_file))))
            return 0
        if args.command == "mcp":
            from harness.interfaces.mcp_server import create_mcp_server

            gateway = AgentRequestGateway(
                Path(args.repo_root),
                allowed_source_roots=[Path(item) for item in (args.allowed_source_roots or [])],
            )
            create_mcp_server(gateway).run(transport="stdio")
            return 0

        if args.command == "api" and args.api_command in {"doctor", "prepare"}:
            source_directory = Path(args.source_directory).resolve()
            harness = Harness(repo_root, allowed_source_roots=[source_directory])
            if args.api_command == "doctor":
                checked = harness.check_api_project(
                    ApiProjectCheckCommand(
                        source_directory=str(source_directory),
                        environment=args.environment,
                    )
                )
                _print(checked)
                return 0 if checked.ready else 2
            _print(
                harness.prepare_api_scenario(
                    ApiScenarioPrepareCommand(
                        source_directory=str(source_directory),
                        goal=args.goal,
                        workspace_id=args.workspace_id,
                        request_id=args.request_id,
                        environment=args.environment,
                        execution_policy=None,
                        quality_policies=args.quality_policies or [],
                    )
                )
            )
            return 0

        harness = Harness(repo_root)
        if args.command == "failure" and args.failure_command == "collect":
            result = harness.collect_failure_logs(
                CollectFailureLogsCommand(
                    workspace_id=args.workspace_id,
                    execution_id=args.execution_id,
                    case_id=args.case_id,
                )
            )
            _print(result)
            return 0 if result.failed == 0 else 1
        if args.command == "failure" and args.failure_command == "analyze":
            result = harness.analyze_failure(
                AnalyzeFailureCommand(
                    workspace_id=args.workspace_id,
                    execution_id=args.execution_id,
                    case_id=args.case_id,
                    collection_id=args.collection_id,
                )
            )
            _print(result)
            return 0 if all(item.analysis_status != "failed" for item in result.analyses) else 1
        if args.command == "failure" and args.failure_command == "report":
            result = harness.prepare_failure_report(
                PrepareFailureReportCommand(
                    workspace_id=args.workspace_id,
                    execution_id=args.execution_id,
                    case_id=args.case_id,
                    collection_id=args.collection_id,
                )
            )
            _print(result)
            return 0
        if args.command == "api" and args.api_command == "run":
            result = harness.run_api_scenario(
                RunApiScenarioCommand(
                    workspace_id=args.workspace_id,
                    execution_id=args.execution_id,
                    environment=args.environment,
                )
            )
            _print(result)
            return 0 if result.status in {"passed", "skipped"} else 1
        if args.command == "api" and args.api_command == "report":
            result = harness.generate_api_allure_report(
                GenerateApiAllureReportCommand(
                    workspace_id=args.workspace_id,
                    execution_id=args.execution_id,
                )
            )
            _print(result)
            return 0 if result.status == "generated" else 1
        if args.command == "api" and args.api_command == "cleanup":
            result = harness.resume_api_cleanup(
                ResumeApiCleanupCommand(
                    workspace_id=args.workspace_id,
                    execution_id=args.execution_id,
                    environment=args.environment,
                )
            )
            _print(result)
            return 0 if result.status == "complete" else 1
        if args.command == "api" and args.api_command == "execute":
            profile = harness.api_execution_profile(args.workspace_id, args.environment)
            _print(
                harness.execute_api_cases(
                    ExecuteApiCasesCommand(
                        workspace_id=args.workspace_id,
                        run_id=args.run_id,
                        cases_path=args.cases_path,
                        execution_profile=profile,
                    )
                )
            )
        elif args.command == "api" and args.api_command == "export-pytest":
            _print(
                harness.export_api_pytest(
                    ExportApiPytestCommand(
                        workspace_id=args.workspace_id,
                        cases_path=args.cases_path,
                        output_path=args.output_path,
                        overwrite=args.overwrite,
                    )
                )
            )
        elif args.command == "workspace":
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
            from harness.testing.evals import run_eval, run_live_eval

            result = (
                run_live_eval(
                    args.case_name,
                    output_root=Path(args.output_dir).resolve() if args.output_dir else None,
                )
                if args.eval_command == "live"
                else run_eval()
            )
            _print(result)
            return 0 if result["passed"] else 1
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
