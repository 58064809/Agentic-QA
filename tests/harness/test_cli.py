from __future__ import annotations

from harness.interfaces.cli import _execution_profile, _parser


def test_run_cli_maps_explicit_execution_profile_arguments() -> None:
    args = _parser().parse_args(
        [
            "run",
            "start",
            "demo",
            "inspect test UI",
            "--artifact",
            "ui_test_draft",
            "--environment",
            "staging",
            "--base-url-env",
            "AGENTIC_QA_BASE_URL",
            "--allow-http-method",
            "GET",
            "--allow-http-method",
            "POST",
            "--allow-ui-mutations",
            "--request-timeout-seconds",
            "30",
        ]
    )

    assert args.environment == "staging"
    assert args.base_url_env == "AGENTIC_QA_BASE_URL"
    assert args.allowed_http_methods == ["GET", "POST"]
    assert args.allow_ui_mutations is True
    assert args.request_timeout_seconds == 30

    profile = _execution_profile(args)
    assert profile.environment == "staging"
    assert profile.base_url_env == "AGENTIC_QA_BASE_URL"
    assert profile.allowed_http_methods == ["GET", "POST"]
    assert profile.allow_ui_mutations is True
    assert profile.request_timeout_seconds == 30


def test_api_cli_exposes_execute_and_deterministic_pytest_export() -> None:
    execute = _parser().parse_args(
        [
            "api",
            "execute",
            "demo",
            "run-api",
            "--environment",
            "qa",
            "--allow-http-method",
            "GET",
            "--allow-http-method",
            "POST",
        ]
    )
    export = _parser().parse_args(["api", "export-pytest", "demo"])

    assert execute.api_command == "execute"
    assert execute.allowed_http_methods == ["GET", "POST"]
    assert export.api_command == "export-pytest"
    assert export.output_path == "exports/api_test_draft/test_api_cases.py"
