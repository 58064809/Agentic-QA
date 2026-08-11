from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import TypeAdapter, ValidationError

from harness.domain.models import (
    ApiLoginRequest,
    ApiLoginRequestEncryption,
    ApiOperationPolicy,
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
    LocalSecretProviderConfig,
    LocalSmsLogin,
    LocalStaticTokenLogin,
)
from harness.domain.security import validate_api_base_url_policy
from harness.infrastructure.secret_provider import (
    SECRET_REFERENCE,
    build_secret_provider,
    parse_secret_reference,
)

LOCAL_CONFIG_NAME = "agentic-qa.local.yml"
LOCAL_CONFIG_EXAMPLE_NAME = "agentic-qa.local.example.yml"
MAX_LOCAL_CONFIG_BYTES = 1024 * 1024
REPARSE_POINT = 0x400
PRODUCTION_ENVIRONMENT_SEGMENTS = {"pro", "prod", "production", "live"}
_SECRET_PROVIDER_ADAPTER = TypeAdapter(LocalSecretProviderConfig)


@dataclass(frozen=True)
class ResolvedApiProject:
    service: str
    environment: str
    source_directory: Path
    policy: ExecutionEnvironmentPolicy
    runtime_values: dict[str, str]
    selected_authentication: str
    structural_sha256: str
    policy_sha256: str


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


def _secret_locations(payload: dict[str, object]) -> list[tuple[tuple[str, ...], str]]:
    locations: list[tuple[tuple[str, ...], str]] = [
        (("postgres", "password"), "postgres.password"),
        (("runtime", "cleanup_journal_key"), "runtime.cleanup_journal_key"),
    ]
    test_management = payload.get("test_management")
    if isinstance(test_management, dict):
        provider = test_management.get("provider")
        if provider == "testrail":
            locations.extend(
                [
                    (("test_management", "username"), "test_management.username"),
                    (("test_management", "api_key"), "test_management.api_key"),
                ]
            )
        elif provider == "qase":
            locations.append((("test_management", "api_token"), "test_management.api_token"))
    api = payload.get("api")
    services = api.get("services") if isinstance(api, dict) else None
    if not isinstance(services, dict):
        return locations
    for service_name, service in services.items():
        environments = service.get("environments") if isinstance(service, dict) else None
        if not isinstance(environments, dict):
            continue
        for environment_name, environment in environments.items():
            auth = environment.get("auth") if isinstance(environment, dict) else None
            if not isinstance(auth, dict):
                continue
            base_path = (
                "api",
                "services",
                str(service_name),
                "environments",
                str(environment_name),
                "auth",
            )
            reference_base = f"api.{service_name}.{environment_name}.auth"
            locations.append((base_path + ("fallback_token",), f"{reference_base}.fallback_token"))
            login = auth.get("login")
            if not isinstance(login, dict):
                continue
            kind = login.get("kind")
            if kind == "sms":
                secret_fields = ("phone", "sms_code")
            elif kind == "password":
                secret_fields = ("username", "password")
            elif kind == "static_token":
                secret_fields = ("token",)
            else:
                secret_fields = ()
            for field in secret_fields:
                locations.append(
                    (
                        base_path + ("login", field),
                        f"{reference_base}.login.{field}",
                    )
                )
            encryption = login.get("encryption")
            if isinstance(encryption, dict):
                locations.append(
                    (
                        base_path + ("login", "encryption", "key"),
                        f"{reference_base}.login.encryption.key",
                    )
                )
    return locations


def _get_nested(payload: dict[str, object], path: tuple[str, ...]) -> object:
    current: object = payload
    for item in path:
        if not isinstance(current, dict) or item not in current:
            raise KeyError(".".join(path))
        current = current[item]
    return current


def _set_nested(payload: dict[str, object], path: tuple[str, ...], value: object) -> None:
    current: object = payload
    for item in path[:-1]:
        if not isinstance(current, dict) or item not in current:
            raise KeyError(".".join(path))
        current = current[item]
    if not isinstance(current, dict):
        raise KeyError(".".join(path))
    current[path[-1]] = value


def _referenced_locations(value: object, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if isinstance(value, str):
        return {path} if SECRET_REFERENCE.fullmatch(value) else set()
    if isinstance(value, dict):
        return set().union(
            *(
                _referenced_locations(item, (*path, str(name)))
                for name, item in value.items()
                if name != "secrets" or path
            ),
            set(),
        )
    if isinstance(value, list):
        return set().union(
            *(_referenced_locations(item, (*path, str(index))) for index, item in enumerate(value)),
            set(),
        )
    return set()


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
        secrets = payload.get("secrets")
        if not isinstance(secrets, dict) or secrets.get("provider") != "local":
            raise ValueError("local configuration example must use the local Secret Provider")
        values = secrets.get("values")
        if not isinstance(values, dict):
            raise ValueError("local Secret Provider values must be an object")
        values["runtime.cleanup_journal_key"] = self._new_cleanup_journal_key()
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
        secrets = payload.get("secrets")
        if not isinstance(secrets, dict) or secrets.get("provider") != "local":
            raise ValueError("runtime key initialization requires the local Secret Provider")
        values = secrets.get("values")
        if not isinstance(values, dict):
            raise ValueError("local Secret Provider values must be an object")
        if str(values.get("runtime.cleanup_journal_key") or "").strip():
            raise FileExistsError("runtime.cleanup_journal_key is already configured")
        values["runtime.cleanup_journal_key"] = self._new_cleanup_journal_key()
        from harness.infrastructure.persistence.common import atomic_text

        atomic_text(
            self.path,
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        )
        return self.path

    def migrate_inline_secrets(self) -> Path:
        """Move legacy inline secret-bearing fields behind local secret references."""
        if not self.path.is_file():
            raise FileNotFoundError(f"local configuration is missing: {self.path}")
        if _is_link_or_reparse(self.path):
            raise ValueError("configuration must not be a link or reparse point")
        payload = yaml.safe_load(self.path.read_bytes().decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("local configuration must contain an object")
        if "secrets" in payload:
            raise FileExistsError("local configuration already declares a Secret Provider")
        values: dict[str, object] = {}
        for path, reference in _secret_locations(payload):
            try:
                value = _get_nested(payload, path)
            except KeyError:
                continue
            values[reference] = value
            _set_nested(payload, path, f"secret://{reference}")
        schema_version = payload.pop("schema_version", "agentic-qa.local-config.v1")
        payload = {
            "schema_version": schema_version,
            "secrets": {"provider": "local", "values": values},
            **payload,
        }
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
        if not isinstance(payload, dict):
            return None, [
                _issue(
                    "LOCAL_CONFIG_INVALID",
                    str(self.path),
                    "local configuration must contain an object",
                    "Fix agentic-qa.local.yml",
                )
            ]
        try:
            provider_config = _SECRET_PROVIDER_ADAPTER.validate_python(payload.get("secrets"))
        except ValidationError as exc:
            issues = []
            for error in exc.errors(include_url=False):
                field = ".".join(str(item) for item in error["loc"])
                issues.append(
                    _issue(
                        "LOCAL_SECRET_PROVIDER_INVALID",
                        f"secrets.{field}" if field else "secrets",
                        str(error["msg"]),
                        "Run `python -m harness config secrets migrate` or fix secrets",
                    )
                )
            return None, issues
        try:
            provider = build_secret_provider(provider_config)
            resolved_payload = copy.deepcopy(payload)
            declared_locations = {path for path, _reference in _secret_locations(resolved_payload)}
            unexpected = sorted(_referenced_locations(resolved_payload) - declared_locations)
            if unexpected:
                raise ValueError("secret reference is not allowed at " + ".".join(unexpected[0]))
            for path, _default_reference in _secret_locations(resolved_payload):
                try:
                    configured_value = _get_nested(resolved_payload, path)
                except KeyError:
                    continue
                reference = parse_secret_reference(configured_value)
                try:
                    secret_value = provider.resolve(reference)
                except KeyError as exc:
                    raise ValueError(f"Secret Provider has no value for {'.'.join(path)}") from exc
                _set_nested(resolved_payload, path, secret_value)
            resolved_payload["secrets"] = {"provider": provider_config.provider}
        except (KeyError, ValueError) as exc:
            return None, [
                _issue(
                    "LOCAL_SECRET_PROVIDER_INVALID",
                    "secrets",
                    str(exc),
                    "Run `python -m harness config secrets migrate` or fix secret references",
                )
            ]
        try:
            config = AgenticQaLocalConfig.model_validate(resolved_payload)
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
        policy_digest = hashlib.sha256(
            json.dumps(
                {
                    "service": service_name,
                    "environment": environment,
                    "policy": policy.model_dump(mode="json", exclude_none=True),
                    "base_url_sha256": hashlib.sha256(value.base_url.encode()).hexdigest(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return ResolvedApiProject(
            service=service_name,
            environment=environment,
            source_directory=self.resolve_source_directory(service.source_directory),
            policy=policy,
            runtime_values=runtime,
            selected_authentication=selected,
            structural_sha256=f"sha256:{digest}",
            policy_sha256=f"sha256:{policy_digest}",
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
        operation_policies = dict(value.operation_policies)
        operation_policies.update(
            {
                operation: ApiOperationPolicy(classification="read_only")
                for operation in value.cleanup_exempt_operations
            }
        )
        return (
            ExecutionEnvironmentPolicy(
                base_url_env=base_name,
                trusted_origins=value.trusted_origins,
                allowed_http_methods=value.allowed_http_methods,
                allow_ui_mutations=False,
                max_request_timeout_seconds=value.timeout_seconds,
                cleanup_exempt_operations=value.cleanup_exempt_operations,
                isolation=value.isolation,
                operation_policies=operation_policies,
                api_auth=authentication,
            ),
            runtime,
            selected,
        )
