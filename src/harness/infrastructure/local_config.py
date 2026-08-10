from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import ValidationError

from harness.domain.models import (
    ApiLoginRequest,
    ApiLoginRequestEncryption,
    ApiTokenInjection,
    ExecutionEnvironmentPolicy,
    LoginApiAuthentication,
    StaticTokenApiAuthentication,
)
from harness.domain.schemas.local_config import (
    AgenticQaLocalConfig,
    LocalApiEnvironment,
    LocalConfigCheckResult,
    LocalConfigIssue,
    LocalPasswordLogin,
    LocalSmsLogin,
    LocalStaticTokenLogin,
)
from harness.domain.security import validate_api_base_url_policy

LOCAL_CONFIG_NAME = "agentic-qa.local.yml"
LOCAL_CONFIG_EXAMPLE_NAME = "agentic-qa.local.example.yml"
MAX_LOCAL_CONFIG_BYTES = 1024 * 1024
REPARSE_POINT = 0x400
PRODUCTION_ENVIRONMENT_SEGMENTS = {"pro", "prod", "production", "live"}


@dataclass(frozen=True)
class ResolvedApiProject:
    service: str
    environment: str
    source_directory: Path
    policy: ExecutionEnvironmentPolicy
    runtime_values: dict[str, str]
    selected_authentication: str
    structural_sha256: str


def _issue(code: str, location: str, message: str, remediation: str) -> LocalConfigIssue:
    return LocalConfigIssue(
        code=code,
        location=location,
        message=message,
        remediation=remediation,
    )


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & REPARSE_POINT
    )


def _production_like(value: str) -> bool:
    segments = set(re.split(r"[^a-z0-9]+", value.strip().casefold()))
    return bool(segments & PRODUCTION_ENVIRONMENT_SEGMENTS)


def _variable(service: str, environment: str, name: str) -> str:
    raw = f"LOCAL_{service}_{environment}_{name}".upper()
    return re.sub(r"[^A-Z0-9_]", "_", raw)


class FilesystemLocalConfigLoader:
    def __init__(self, repo_root: Path | str) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.path = self.repo_root / LOCAL_CONFIG_NAME
        self.example_path = self.repo_root / LOCAL_CONFIG_EXAMPLE_NAME

    def init(self) -> Path:
        if self.path.exists():
            raise FileExistsError(f"local configuration already exists: {self.path}")
        if not self.example_path.is_file():
            raise FileNotFoundError(f"local configuration example is missing: {self.example_path}")
        if _is_link_or_reparse(self.example_path):
            raise ValueError("local configuration example must not be a link or reparse point")
        raw = self.example_path.read_bytes()
        if len(raw) > MAX_LOCAL_CONFIG_BYTES:
            raise ValueError("local configuration example exceeds size limit")
        payload = yaml.safe_load(raw.decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("local configuration example must contain an object")
        runtime = payload.setdefault("runtime", {})
        if not isinstance(runtime, dict):
            raise ValueError("local configuration runtime section must be an object")
        runtime["cleanup_journal_key"] = self._new_cleanup_journal_key()
        rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).encode("utf-8")
        with self.path.open("xb") as handle:
            handle.write(rendered)
        return self.path

    @staticmethod
    def _new_cleanup_journal_key() -> str:
        return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")

    def init_runtime_key(self) -> Path:
        if not self.path.is_file():
            raise FileNotFoundError(f"local configuration is missing: {self.path}")
        if _is_link_or_reparse(self.path):
            raise ValueError("configuration must not be a link or reparse point")
        raw = self.path.read_bytes()
        payload = yaml.safe_load(raw.decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("local configuration must contain an object")
        runtime = payload.setdefault("runtime", {})
        if not isinstance(runtime, dict):
            raise ValueError("local configuration runtime section must be an object")
        if str(runtime.get("cleanup_journal_key") or "").strip():
            raise FileExistsError("runtime.cleanup_journal_key is already configured")
        runtime["cleanup_journal_key"] = self._new_cleanup_journal_key()
        from harness.infrastructure.persistence.common import atomic_text

        atomic_text(
            self.path,
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        )
        return self.path

    def check(self) -> LocalConfigCheckResult:
        _, issues = self._load()
        return LocalConfigCheckResult(
            ready=not issues,
            config_path=str(self.path),
            issues=issues,
        )

    def load_required(self) -> AgenticQaLocalConfig:
        config, issues = self._load()
        if config is None or issues:
            details = "; ".join(
                f"{item.code} at {item.location}: {item.remediation}" for item in issues
            )
            raise ValueError(f"local configuration check failed: {details}")
        return config

    def load_with_issues(
        self,
    ) -> tuple[AgenticQaLocalConfig | None, list[LocalConfigIssue]]:
        """Load without raising so doctor-style entry points can report every issue."""
        return self._load()

    def _load(self) -> tuple[AgenticQaLocalConfig | None, list[LocalConfigIssue]]:
        if not self.path.is_file():
            return None, [
                _issue(
                    "LOCAL_CONFIG_MISSING",
                    str(self.path),
                    "required project-local configuration is missing",
                    "Run `python -m harness config init`, then edit agentic-qa.local.yml",
                )
            ]
        try:
            if _is_link_or_reparse(self.path):
                raise ValueError("configuration must not be a link or reparse point")
            raw = self.path.read_bytes()
            if len(raw) > MAX_LOCAL_CONFIG_BYTES:
                raise ValueError(f"configuration exceeds {MAX_LOCAL_CONFIG_BYTES} bytes")
            payload = yaml.safe_load(raw.decode("utf-8-sig"))
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            return None, [
                _issue(
                    "LOCAL_CONFIG_INVALID",
                    str(self.path),
                    f"local configuration is invalid: {exc}",
                    "Fix the reported field so the file conforms to agentic-qa.local-config.v1",
                )
            ]
        try:
            config = AgenticQaLocalConfig.model_validate(payload)
        except ValidationError as exc:
            issues = []
            for error in exc.errors(include_url=False):
                field = ".".join(str(item) for item in error["loc"])
                issues.append(
                    _issue(
                        "LOCAL_CONFIG_INVALID",
                        field or str(self.path),
                        str(error["msg"]),
                        f"Fix {field or self.path} in agentic-qa.local.yml",
                    )
                )
            return None, issues
        issues = self._semantic_issues(config)
        return config, issues

    def _semantic_issues(self, config: AgenticQaLocalConfig) -> list[LocalConfigIssue]:
        issues: list[LocalConfigIssue] = []
        if not os.environ.get(config.model.api_key_env, "").strip():
            issues.append(
                _issue(
                    "MODEL_API_KEY_MISSING",
                    "model.api_key_env",
                    f"model key environment variable is empty: {config.model.api_key_env}",
                    f"Set only the actual model key in {config.model.api_key_env}",
                )
            )
        if (
            config.rag.provider == "openai-compatible"
            and not os.environ.get(config.rag.api_key_env, "").strip()
        ):
            issues.append(
                _issue(
                    "RAG_API_KEY_MISSING",
                    "rag.api_key_env",
                    f"RAG key environment variable is empty: {config.rag.api_key_env}",
                    f"Set only the actual RAG key in {config.rag.api_key_env}",
                )
            )
        if not config.postgres.password:
            issues.append(
                _issue(
                    "POSTGRES_PASSWORD_MISSING",
                    "postgres.password",
                    "PostgreSQL password is empty",
                    "Set postgres.password in agentic-qa.local.yml",
                )
            )
        issues.extend(self._connection_url_issues(config))
        seen: dict[str, str] = {}
        for index, raw_root in enumerate(config.workspace_defaults.additional_source_roots):
            try:
                self.resolve_source_directory(raw_root)
            except (OSError, ValueError) as exc:
                issues.append(
                    _issue(
                        "ADDITIONAL_SOURCE_ROOT_INVALID",
                        f"workspace_defaults.additional_source_roots.{index}",
                        str(exc),
                        "Use an existing non-linked directory below the repository root",
                    )
                )
        for service, value in config.api.services.items():
            location = f"api.services.{service}.source_directory"
            try:
                source = self.resolve_source_directory(value.source_directory)
                key = os.path.normcase(str(source))
                if key in seen:
                    issues.append(
                        _issue(
                            "API_SOURCE_DIRECTORY_DUPLICATE",
                            location,
                            f"source directory is already assigned to {seen[key]}",
                            "Assign each API source directory to exactly one service",
                        )
                    )
                else:
                    seen[key] = service
            except (OSError, ValueError) as exc:
                issues.append(
                    _issue(
                        "API_SOURCE_DIRECTORY_INVALID",
                        location,
                        str(exc),
                        "Use an existing non-linked directory below the repository root",
                    )
                )
            for environment, environment_config in value.environments.items():
                issues.extend(
                    self._api_environment_issues(service, environment, environment_config)
                )
        return issues

    @staticmethod
    def _connection_url_issues(config: AgenticQaLocalConfig) -> list[LocalConfigIssue]:
        values: list[tuple[str, str | None]] = [("model.base_url", config.model.base_url)]
        if config.rag.provider == "openai-compatible":
            values.append(("rag.base_url", config.rag.base_url))
        provider = config.test_management
        if hasattr(provider, "base_url"):
            values.append(("test_management.base_url", provider.base_url))
        issues: list[LocalConfigIssue] = []
        for location, value in values:
            if value is None:
                continue
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                issues.append(
                    _issue(
                        "LOCAL_CONNECTION_URL_INVALID",
                        location,
                        "connection URL must be HTTPS without credentials, query, or fragment",
                        f"Fix {location} in agentic-qa.local.yml",
                    )
                )
        return issues

    def resolve_source_directory(self, value: str) -> Path:
        relative = Path(value)
        if relative.is_absolute():
            raise ValueError("source_directory must be relative to the repository root")
        target = (self.repo_root / relative).resolve(strict=True)
        if self.repo_root != target and self.repo_root not in target.parents:
            raise ValueError("source_directory escapes the repository root")
        cursor = self.repo_root
        for part in relative.parts:
            cursor /= part
            if _is_link_or_reparse(cursor):
                raise ValueError("source_directory contains a link or reparse point")
        if not target.is_dir():
            raise ValueError("source_directory is not a directory")
        return target

    def _api_environment_issues(
        self,
        service: str,
        environment: str,
        value: LocalApiEnvironment,
    ) -> list[LocalConfigIssue]:
        location = f"api.services.{service}.environments.{environment}"
        issues: list[LocalConfigIssue] = []
        if _production_like(environment):
            issues.append(
                _issue(
                    "API_PRODUCTION_UNSUPPORTED",
                    location,
                    f"production-like API environment is not supported: {environment}",
                    "Use a dev, test, QA, staging, or other non-production environment",
                )
            )
        try:
            validate_api_base_url_policy(value.base_url, trusted_origins=value.trusted_origins)
        except ValueError as exc:
            issues.append(
                _issue(
                    "API_BASE_URL_INVALID",
                    f"{location}.base_url",
                    str(exc),
                    "Set an HTTPS Base URL whose Origin appears in trusted_origins",
                )
            )
        login = value.auth.login
        if isinstance(login, LocalSmsLogin):
            configured = [
                bool(login.tel_code.strip()),
                bool(login.phone.strip()),
                bool(login.sms_code),
            ]
            if any(configured) and not all(configured):
                issues.append(
                    _issue(
                        "API_LOGIN_CREDENTIAL_PARTIAL",
                        f"{location}.auth.login",
                        "SMS login credentials are only partially configured",
                        "Fill tel_code, phone, and sms_code, or clear all and set fallback_token",
                    )
                )
            elif all(configured):
                if environment.casefold() in {"dev", "test"} and login.sms_code != "000000":
                    issues.append(
                        _issue(
                            "API_SMS_CODE_INVALID_FOR_ENV",
                            f"{location}.auth.login.sms_code",
                            f"{environment} SMS code must be 000000",
                            "Set sms_code to 000000",
                        )
                    )
                if login.encryption is not None and len(login.encryption.key.encode()) != 16:
                    issues.append(
                        _issue(
                            "API_LOGIN_ENCRYPTION_KEY_INVALID",
                            f"{location}.auth.login.encryption.key",
                            "AES-128 key must encode to exactly 16 bytes",
                            "Set a confirmed 16-byte test-environment encryption key",
                        )
                    )
            elif not value.auth.fallback_token.strip():
                issues.append(
                    _issue(
                        "API_AUTH_FALLBACK_TOKEN_MISSING",
                        f"{location}.auth.fallback_token",
                        "login is empty and fallback Token is empty",
                        "Fill all login credentials or set fallback_token",
                    )
                )
        elif isinstance(login, LocalPasswordLogin):
            configured = [bool(login.username.strip()), bool(login.password)]
            if any(configured) and not all(configured):
                issues.append(
                    _issue(
                        "API_LOGIN_CREDENTIAL_PARTIAL",
                        f"{location}.auth.login",
                        "password login credentials are only partially configured",
                        "Fill username and password, or clear both and set fallback_token",
                    )
                )
            elif all(configured) and login.encryption is not None:
                if len(login.encryption.key.encode()) != 16:
                    issues.append(
                        _issue(
                            "API_LOGIN_ENCRYPTION_KEY_INVALID",
                            f"{location}.auth.login.encryption.key",
                            "AES-128 key must encode to exactly 16 bytes",
                            "Set a confirmed 16-byte test-environment encryption key",
                        )
                    )
            elif not any(configured) and not value.auth.fallback_token.strip():
                issues.append(
                    _issue(
                        "API_AUTH_FALLBACK_TOKEN_MISSING",
                        f"{location}.auth.fallback_token",
                        "login is empty and fallback Token is empty",
                        "Fill all login credentials or set fallback_token",
                    )
                )
        elif isinstance(login, LocalStaticTokenLogin) and not login.token.strip():
            issues.append(
                _issue(
                    "API_STATIC_TOKEN_MISSING",
                    f"{location}.auth.login.token",
                    "static Token is empty",
                    "Set auth.login.token or use fallback_token",
                )
            )
        return issues

    def find_api_project(
        self,
        config: AgenticQaLocalConfig,
        source_directory: Path | str,
        environment: str,
    ) -> ResolvedApiProject:
        requested = Path(source_directory).resolve()
        matches = [
            (name, service)
            for name, service in config.api.services.items()
            if self.resolve_source_directory(service.source_directory) == requested
        ]
        if len(matches) != 1:
            raise ValueError(
                "source directory must match exactly one api.services.<service>.source_directory"
            )
        service_name, service = matches[0]
        if environment not in service.environments:
            raise ValueError(f"environment is not declared for {service_name}: {environment}")
        return self.resolve_api_project(config, service_name, environment)

    def resolve_api_project(
        self,
        config: AgenticQaLocalConfig,
        service_name: str,
        environment: str,
    ) -> ResolvedApiProject:
        try:
            service = config.api.services[service_name]
            value = service.environments[environment]
        except KeyError as exc:
            raise ValueError(
                f"unknown API service/environment: {service_name}/{environment}"
            ) from exc
        policy, runtime, selected = self._policy(service_name, environment, value)
        structural = {
            "service": service_name,
            "environment": environment,
            "source_directory": service.source_directory.replace("\\", "/"),
            "policy": policy.model_dump(mode="json", exclude_none=True),
            "base_url_sha256": hashlib.sha256(value.base_url.encode()).hexdigest(),
        }
        digest = hashlib.sha256(
            json.dumps(structural, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return ResolvedApiProject(
            service=service_name,
            environment=environment,
            source_directory=self.resolve_source_directory(service.source_directory),
            policy=policy,
            runtime_values=runtime,
            selected_authentication=selected,
            structural_sha256=f"sha256:{digest}",
        )

    @staticmethod
    def _policy(
        service: str,
        environment: str,
        value: LocalApiEnvironment,
    ) -> tuple[ExecutionEnvironmentPolicy, dict[str, str], str]:
        base_name = _variable(service, environment, "BASE_URL")
        runtime = {base_name: value.base_url}
        login = value.auth.login
        authentication: LoginApiAuthentication | StaticTokenApiAuthentication
        selected: str
        if isinstance(login, LocalSmsLogin) and all(
            (login.tel_code.strip(), login.phone.strip(), login.sms_code)
        ):
            tel_name = _variable(service, environment, "TEL_CODE")
            phone_name = _variable(service, environment, "PHONE")
            sms_name = _variable(service, environment, "SMS_CODE")
            runtime.update(
                {tel_name: login.tel_code, phone_name: login.phone, sms_name: login.sms_code}
            )
            request_encryption = None
            if login.encryption is not None:
                key_name = _variable(service, environment, "LOGIN_ENCRYPTION_KEY")
                runtime[key_name] = login.encryption.key
                request_encryption = ApiLoginRequestEncryption(
                    algorithm=login.encryption.algorithm,
                    key_env=key_name,
                    fields=login.encryption.fields,
                )
            authentication = LoginApiAuthentication(
                mode="login",
                request=ApiLoginRequest(
                    method="POST",
                    path=login.request_path,
                    headers=login.request_headers,
                    body={
                        "telCode": f"${{{tel_name}}}",
                        "phone": f"${{{phone_name}}}",
                        "smsCode": f"${{{sms_name}}}",
                        **dict.fromkeys(login.null_body_fields),
                    },
                ),
                token_json_path=login.token_json_path,
                expected_status_codes=login.expected_status_codes,
                injection=login.injection,
                request_encryption=request_encryption,
                success_condition=login.success_condition,
            )
            selected = "sms"
        elif isinstance(login, LocalPasswordLogin) and login.username.strip() and login.password:
            username_name = _variable(service, environment, "USERNAME")
            password_name = _variable(service, environment, "PASSWORD")
            runtime.update({username_name: login.username, password_name: login.password})
            request_encryption = None
            if login.encryption is not None:
                key_name = _variable(service, environment, "LOGIN_ENCRYPTION_KEY")
                runtime[key_name] = login.encryption.key
                request_encryption = ApiLoginRequestEncryption(
                    algorithm=login.encryption.algorithm,
                    key_env=key_name,
                    fields=login.encryption.fields,
                )
            authentication = LoginApiAuthentication(
                mode="login",
                request=ApiLoginRequest(
                    method="POST",
                    path=login.request_path,
                    headers=login.request_headers,
                    body={
                        "username": f"${{{username_name}}}",
                        "password": f"${{{password_name}}}",
                    },
                ),
                token_json_path=login.token_json_path,
                expected_status_codes=login.expected_status_codes,
                injection=login.injection,
                request_encryption=request_encryption,
                success_condition=login.success_condition,
            )
            selected = "password"
        elif isinstance(login, LocalStaticTokenLogin) and login.token.strip():
            token_name = _variable(service, environment, "STATIC_TOKEN")
            runtime[token_name] = login.token
            authentication = StaticTokenApiAuthentication(
                mode="static_token", token_env=token_name, injection=login.injection
            )
            selected = "static_token"
        else:
            token_name = _variable(service, environment, "FALLBACK_TOKEN")
            runtime[token_name] = value.auth.fallback_token
            authentication = StaticTokenApiAuthentication(
                mode="static_token",
                token_env=token_name,
                injection=value.auth.fallback_injection
                or getattr(login, "injection", None)
                or ApiTokenInjection(),
            )
            selected = "static_token"
        return (
            ExecutionEnvironmentPolicy(
                base_url_env=base_name,
                trusted_origins=value.trusted_origins,
                allowed_http_methods=value.allowed_http_methods,
                allow_ui_mutations=False,
                max_request_timeout_seconds=value.timeout_seconds,
                cleanup_exempt_operations=value.cleanup_exempt_operations,
                api_auth=authentication,
            ),
            runtime,
            selected,
        )
