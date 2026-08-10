from __future__ import annotations

import hashlib
import stat
from pathlib import Path

from pydantic import ValidationError

from harness.application.source import (
    SourceBundle,
    SourceCompleteness,
    SourceDocument,
    SourceIngestionLimits,
)
from harness.domain.schemas.api_project import (
    ApiProjectCheckCommand,
    ApiProjectCheckResult,
    ApiProjectIssue,
)
from harness.infrastructure.api_scenario_sources import inspect_api_scenario_sources
from harness.infrastructure.local_config import FilesystemLocalConfigLoader

PROJECT_CONFIG_NAME = "api-test.yml"
MAX_PROJECT_FILES = 256
MAX_PROJECT_FILE_BYTES = 16 * 1024 * 1024
MAX_PROJECT_TOTAL_BYTES = 64 * 1024 * 1024
REPARSE_POINT = 0x400


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _issue(code: str, location: str, message: str, remediation: str) -> ApiProjectIssue:
    return ApiProjectIssue(
        code=code,
        location=location,
        message=message,
        remediation=remediation,
    )


class FilesystemApiProjectChecker:
    """Check one configured API service without exposing local values."""

    def __init__(self, repo_root: Path | str = ".") -> None:
        self._loader = FilesystemLocalConfigLoader(repo_root)

    def check(self, command: ApiProjectCheckCommand) -> ApiProjectCheckResult:
        source = Path(command.source_directory).resolve()
        issues: list[ApiProjectIssue] = []
        config, local_issues = self._loader.load_with_issues()
        issues.extend(
            _issue(item.code, item.location, item.message, item.remediation)
            for item in local_issues
        )
        legacy = source / PROJECT_CONFIG_NAME
        if legacy.exists():
            issues.append(
                _issue(
                    "API_LEGACY_CONFIG_PRESENT",
                    str(legacy),
                    "service-directory api-test.yml is no longer accepted",
                    "Move all values to agentic-qa.local.yml and remove api-test.yml",
                )
            )
        project = None
        if config is not None:
            try:
                project = self._loader.find_api_project(config, source, command.environment)
            except ValueError as exc:
                issues.append(
                    _issue(
                        "API_PROJECT_NOT_CONFIGURED",
                        "api.services",
                        str(exc),
                        "Set api.services.<service>.source_directory and declare the environment",
                    )
                )
        if source.is_dir():
            issues.extend(self._inspect_sources(source))
        else:
            issues.append(
                _issue(
                    "API_SOURCE_DIRECTORY_MISSING",
                    str(source),
                    "API source directory does not exist or is not a directory",
                    "Create the configured directory and add OpenAPI plus manual cases",
                )
            )
        if command.execution_policy is not None:
            issues.append(
                _issue(
                    "API_INLINE_POLICY_UNSUPPORTED",
                    "execution_policy",
                    "inline API policy is no longer supported",
                    "Configure the environment only in agentic-qa.local.yml",
                )
            )
        return ApiProjectCheckResult(
            ready=not issues and project is not None,
            service=project.service if project else None,
            environment=command.environment,
            config_path=str(self._loader.path),
            selected_authentication=project.selected_authentication if project else None,
            issues=issues,
            execution_policy=project.policy if not issues and project else None,
            structural_sha256=project.structural_sha256 if not issues and project else None,
        )

    @staticmethod
    def _inspect_sources(source: Path) -> list[ApiProjectIssue]:
        documents: list[SourceDocument] = []
        raw_parts: list[bytes] = []
        total = 0
        try:
            entries = sorted(source.iterdir(), key=lambda item: item.name.casefold())
            regular = [item for item in entries if item.name != PROJECT_CONFIG_NAME]
            if len(regular) > MAX_PROJECT_FILES:
                raise ValueError(f"source file count exceeds {MAX_PROJECT_FILES}")
            for item in regular:
                info = item.lstat()
                if stat.S_ISLNK(info.st_mode) or bool(
                    getattr(info, "st_file_attributes", 0) & REPARSE_POINT
                ):
                    raise ValueError(f"source file must not be a link: {item.name}")
                if stat.S_ISDIR(info.st_mode):
                    continue
                if not stat.S_ISREG(info.st_mode):
                    continue
                if info.st_size > MAX_PROJECT_FILE_BYTES:
                    raise ValueError(
                        f"source file exceeds {MAX_PROJECT_FILE_BYTES} bytes: {item.name}"
                    )
                total += info.st_size
                if total > MAX_PROJECT_TOTAL_BYTES:
                    raise ValueError(f"source total exceeds {MAX_PROJECT_TOTAL_BYTES} bytes")
                raw = item.read_bytes()
                raw_parts.append(raw)
                try:
                    text = raw.decode("utf-8-sig")
                    completeness = SourceCompleteness.COMPLETE
                except UnicodeError:
                    text = None
                    completeness = SourceCompleteness.UNAVAILABLE
                digest = _sha256(raw)
                documents.append(
                    SourceDocument(
                        path=item.name,
                        raw_sha256=digest,
                        parsed_sha256=digest if text is not None else None,
                        byte_size=len(raw),
                        text=text,
                        completeness=completeness,
                    )
                )
            bundle = SourceBundle(
                parser_version="api-project-preflight-v2",
                limits=SourceIngestionLimits(),
                documents=tuple(documents),
                completeness=SourceCompleteness.COMPLETE,
                bundle_hash=_sha256(b"".join(raw_parts)),
            )
            inspection = inspect_api_scenario_sources(bundle, require_complete=False)
        except (OSError, UnicodeError, ValueError, ValidationError) as exc:
            return [
                _issue(
                    "API_SOURCE_INVALID",
                    str(source),
                    f"API source directory cannot be validated: {exc}",
                    "Fix the OpenAPI/manual source files before running api prepare",
                )
            ]
        issues: list[ApiProjectIssue] = []
        if not inspection.summary.openapi_files:
            issues.append(
                _issue(
                    "API_OPENAPI_MISSING",
                    str(source),
                    "no complete self-contained OpenAPI 3.x or Swagger 2.0 document was found",
                    "Export a complete Apifox OpenAPI document into the service directory",
                )
            )
        if not inspection.summary.manual_case_files:
            issues.append(
                _issue(
                    "API_MANUAL_CASES_MISSING",
                    str(source),
                    "no valid 11-column manual API test-case file was found",
                    "Add CSV, Markdown, or agentic-qa.test-case-set.v1 YAML manual cases",
                )
            )
        return issues
