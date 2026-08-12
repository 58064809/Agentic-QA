from __future__ import annotations

import base64
import re
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator

from harness.domain.models import (
    ApiIsolationPolicy,
    ApiLoginSuccessCondition,
    ApiOperationPolicy,
    ApiTokenInjection,
    StrictModel,
)
from harness.domain.security import validate_api_base_url_policy, validate_api_trusted_origin

ENV_NAME_PATTERN = r"^[A-Z_][A-Z0-9_]*$"


class LocalMappingSecretProviderConfig(StrictModel):
    provider: Literal["local"] = "local"
    values: dict[str, SecretStr] = Field(default_factory=dict)


class EnvironmentSecretProviderConfig(StrictModel):
    provider: Literal["environment"]
    variables: dict[str, str] = Field(default_factory=dict)

    @field_validator("variables")
    @classmethod
    def validate_environment_names(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not re.fullmatch(ENV_NAME_PATTERN, name) for name in value.values()):
            raise ValueError("secret provider environment names must be uppercase identifiers")
        return value


LocalSecretProviderConfig = Annotated[
    LocalMappingSecretProviderConfig | EnvironmentSecretProviderConfig,
    Field(discriminator="provider"),
]


class SecretProviderDescriptor(StrictModel):
    provider: Literal["local", "environment"]


class LocalModelConfig(StrictModel):
    provider: str = Field(min_length=1)
    api_key_env: str = Field(pattern=ENV_NAME_PATTERN)
    flash_model: str = Field(min_length=1)
    pro_model: str = Field(min_length=1)
    base_url: str | None = None
    timeout_seconds: float = Field(default=180, gt=0, le=600)
    max_output_tokens: int = Field(default=16384, ge=256, le=131072)


class LocalRagConfig(StrictModel):
    provider: Literal["local-lexical", "openai-compatible"] = "local-lexical"
    api_key_env: str = Field(default="RAG_API_KEY", pattern=ENV_NAME_PATTERN)
    base_url: str | None = None
    model: str = Field(default="text-embedding-3-small", min_length=1)
    chunk_size: int = Field(default=1200, ge=200, le=4000)
    chunk_overlap: int = Field(default=400, ge=0, le=1000)

    @model_validator(mode="after")
    def validate_overlap(self) -> LocalRagConfig:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("rag.chunk_overlap must be smaller than rag.chunk_size")
        if self.provider == "openai-compatible" and not self.base_url:
            raise ValueError("openai-compatible RAG requires rag.base_url")
        return self


class LocalPostgresConfig(StrictModel):
    host: str = Field(min_length=1)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1)
    user: str = Field(min_length=1)
    password: str
    connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    statement_timeout_ms: int = Field(default=10000, ge=100, le=60000)
    max_rows: int = Field(default=200, ge=1, le=1000)


class NoTestManagementConfig(StrictModel):
    provider: Literal["none"] = "none"


class LocalTestRailConfig(StrictModel):
    provider: Literal["testrail"]
    base_url: str = Field(min_length=1)
    username: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    timeout_seconds: int = Field(default=10, ge=1, le=30)
    max_items: int = Field(default=250, ge=1, le=250)
    max_response_bytes: int = Field(default=1_048_576, ge=1024, le=2_097_152)


class LocalQaseConfig(StrictModel):
    provider: Literal["qase"]
    base_url: str = Field(min_length=1)
    api_token: str = Field(min_length=1)
    timeout_seconds: int = Field(default=10, ge=1, le=30)
    max_items: int = Field(default=100, ge=1, le=100)
    max_response_bytes: int = Field(default=1_048_576, ge=1024, le=2_097_152)


LocalTestManagementConfig = Annotated[
    NoTestManagementConfig | LocalTestRailConfig | LocalQaseConfig,
    Field(discriminator="provider"),
]


class LocalWorkspaceDefaults(StrictModel):
    quality_policies: list[str] = Field(default_factory=list)
    additional_source_roots: list[str] = Field(default_factory=list)

    @field_validator("quality_policies", "additional_source_roots")
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("values must be unique")
        return normalized


class LocalRuntimeConfig(StrictModel):
    cleanup_journal_key: str = ""

    @field_validator("cleanup_journal_key")
    @classmethod
    def validate_cleanup_journal_key(cls, value: str) -> str:
        if not value:
            return value
        try:
            decoded = base64.urlsafe_b64decode(value.encode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise ValueError("cleanup_journal_key must be URL-safe base64") from exc
        if len(decoded) != 32:
            raise ValueError("cleanup_journal_key must decode to exactly 32 bytes")
        return value


class LocalLogQueryLimits(StrictModel):
    default_window_seconds: int = Field(default=30, ge=1, le=300)
    max_window_seconds: int = Field(default=300, ge=1, le=300)
    default_max_entries: int = Field(default=1000, ge=1, le=5000)
    hard_max_entries: int = Field(default=5000, ge=1, le=5000)
    max_response_bytes: int = Field(default=8_388_608, ge=1024, le=16_777_216)

    @model_validator(mode="after")
    def validate_defaults(self) -> LocalLogQueryLimits:
        if self.default_window_seconds > self.max_window_seconds:
            raise ValueError("logs default window exceeds max window")
        if self.default_max_entries > self.hard_max_entries:
            raise ValueError("logs default entries exceeds hard max entries")
        return self


class LocalLogFileService(StrictModel):
    files: list[str] = Field(min_length=1)

    @field_validator("files")
    @classmethod
    def validate_file_patterns(cls, value: list[str]) -> list[str]:
        normalized = [item.strip().replace("\\", "/") for item in value if item.strip()]
        if (
            not normalized
            or len(normalized) != len(set(normalized))
            or any(
                not item.startswith("local-logs/")
                or item.startswith("local-logs//")
                or ".." in item.split("/")
                or ":" in item
                for item in normalized
            )
        ):
            raise ValueError("local log patterns must be unique paths below local-logs/")
        return normalized


class LocalFileLogProvider(StrictModel):
    services: dict[str, LocalLogFileService] = Field(default_factory=dict)
    max_files: int = Field(default=100, ge=1, le=1000)
    max_file_bytes: int = Field(default=4_194_304, ge=1024, le=16_777_216)


class LocalLokiLogProvider(StrictModel):
    base_url: str
    trusted_origins: list[str] = Field(min_length=1)
    token: str
    service_label: str = "app"
    environment_label: str = "environment"
    timeout_seconds: int = Field(default=15, ge=1, le=60)

    @field_validator("trusted_origins")
    @classmethod
    def normalize_trusted_origins(cls, value: list[str]) -> list[str]:
        origins = list(dict.fromkeys(validate_api_trusted_origin(item) for item in value))
        if len(origins) != len(value):
            raise ValueError("logs.loki.trusted_origins must be unique HTTPS origins")
        return origins

    @field_validator("service_label", "environment_label")
    @classmethod
    def validate_label_name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("Loki label names must be identifiers")
        return value

    @model_validator(mode="after")
    def validate_connection(self) -> LocalLokiLogProvider:
        validate_api_base_url_policy(self.base_url, trusted_origins=self.trusted_origins)
        if not self.token.strip():
            raise ValueError("logs.loki.token cannot be empty")
        return self


class LocalLogsConfig(StrictModel):
    provider: Literal["none", "local-file", "loki"] = "none"
    allowed_environments: list[str] = Field(
        default_factory=lambda: ["dev", "test", "qa", "staging"]
    )
    query: LocalLogQueryLimits = Field(default_factory=LocalLogQueryLimits)
    api_service_scopes: dict[str, list[str]] = Field(default_factory=dict)
    local_file: LocalFileLogProvider | None = None
    loki: LocalLokiLogProvider | None = None

    @field_validator("allowed_environments")
    @classmethod
    def normalize_environments(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip().casefold() for item in value if item.strip()))
        if len(normalized) != len(value):
            raise ValueError("logs.allowed_environments must be unique non-empty names")
        return normalized

    @field_validator("api_service_scopes")
    @classmethod
    def normalize_scopes(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        normalized: dict[str, list[str]] = {}
        for api_service, services in value.items():
            key = api_service.strip()
            items = list(dict.fromkeys(item.strip() for item in services if item.strip()))
            if not key or not items:
                raise ValueError("log service scopes require non-empty API and log services")
            normalized[key] = items
        return normalized

    @model_validator(mode="after")
    def validate_provider(self) -> LocalLogsConfig:
        if self.provider == "local-file" and self.local_file is None:
            raise ValueError("logs.provider local-file requires logs.local_file")
        if self.provider == "loki" and self.loki is None:
            raise ValueError("logs.provider loki requires logs.loki")
        return self


class LocalApiEncryption(StrictModel):
    algorithm: Literal["aes-128-cbc-pkcs7-base64-iv-prefix"]
    key: str
    fields: list[str] = Field(min_length=1)

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: list[str]) -> list[str]:
        fields = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if not fields or any(not item.replace("-", "_").isidentifier() for item in fields):
            raise ValueError("encryption fields must be unique root JSON field names")
        return fields


class LocalPasswordLogin(StrictModel):
    kind: Literal["password"]
    request_path: str = Field(min_length=1)
    username: str
    password: str
    token_json_path: str = Field(pattern=r"^\$(?:\.[A-Za-z_][A-Za-z0-9_-]*)+$")
    expected_status_codes: list[int] = Field(default_factory=lambda: [200], min_length=1)
    request_headers: dict[str, str] = Field(default_factory=dict)
    injection: ApiTokenInjection = Field(default_factory=ApiTokenInjection)
    encryption: LocalApiEncryption | None = None
    success_condition: ApiLoginSuccessCondition | None = None


class LocalSmsLogin(StrictModel):
    kind: Literal["sms"]
    request_path: str = Field(min_length=1)
    tel_code: str
    phone: str
    sms_code: str
    token_json_path: str = Field(pattern=r"^\$(?:\.[A-Za-z_][A-Za-z0-9_-]*)+$")
    expected_status_codes: list[int] = Field(default_factory=lambda: [200], min_length=1)
    request_headers: dict[str, str] = Field(default_factory=dict)
    null_body_fields: list[str] = Field(default_factory=list)
    injection: ApiTokenInjection = Field(default_factory=ApiTokenInjection)
    encryption: LocalApiEncryption | None = None
    success_condition: ApiLoginSuccessCondition | None = None


class LocalStaticTokenLogin(StrictModel):
    kind: Literal["static_token"]
    token: str
    injection: ApiTokenInjection = Field(default_factory=ApiTokenInjection)


LocalApiLogin = Annotated[
    LocalPasswordLogin | LocalSmsLogin | LocalStaticTokenLogin,
    Field(discriminator="kind"),
]


class LocalApiAuthentication(StrictModel):
    login: LocalApiLogin | None = None
    fallback_token: str = ""
    fallback_injection: ApiTokenInjection | None = None

    @model_validator(mode="after")
    def require_source(self) -> LocalApiAuthentication:
        if self.login is None and not self.fallback_token.strip():
            raise ValueError("auth requires login or fallback_token")
        return self


class LocalApiEnvironment(StrictModel):
    base_url: str = Field(min_length=1)
    trusted_origins: list[str] = Field(min_length=1)
    allowed_http_methods: list[str] = Field(min_length=1)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    cleanup_exempt_operations: list[str] = Field(default_factory=list)
    isolation: ApiIsolationPolicy = Field(default_factory=ApiIsolationPolicy)
    operation_policies: dict[str, ApiOperationPolicy] = Field(default_factory=dict)
    correlation_response_headers: list[str] = Field(default_factory=list)
    auth: LocalApiAuthentication

    @model_validator(mode="after")
    def reject_duplicate_operation_policy_sources(self) -> LocalApiEnvironment:
        overlap = sorted(set(self.cleanup_exempt_operations) & set(self.operation_policies))
        if overlap:
            raise ValueError(
                "cleanup_exempt_operations and operation_policies overlap: " + ", ".join(overlap)
            )
        return self

    @field_validator("cleanup_exempt_operations")
    @classmethod
    def normalize_cleanup_exempt_operations(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            method, separator, path = item.strip().partition(" ")
            canonical = f"{method.upper()} {path}"
            if not separator or method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
                raise ValueError("cleanup exemptions must use canonical mutating METHOD /path")
            if not path.startswith("/") or " " in path:
                raise ValueError("cleanup exemption path must be a relative path template")
            normalized.append(canonical)
        if len(normalized) != len(set(normalized)):
            raise ValueError("cleanup exemptions must be unique")
        return normalized

    @field_validator("allowed_http_methods")
    @classmethod
    def normalize_methods(cls, value: list[str]) -> list[str]:
        methods = list(dict.fromkeys(item.strip().upper() for item in value if item.strip()))
        if not methods:
            raise ValueError("allowed_http_methods cannot be empty")
        return methods

    @field_validator("correlation_response_headers")
    @classmethod
    def normalize_correlation_headers(cls, value: list[str]) -> list[str]:
        from harness.domain.security import HTTP_HEADER_NAME, SECRET_KEY

        builtin = {
            "traceparent",
            "x-trace-id",
            "x-request-id",
            "request-id",
            "x-correlation-id",
            "x-tid",
            "tid",
        }
        normalized = list(dict.fromkeys(item.strip().casefold() for item in value if item.strip()))
        invalid = [
            item
            for item in normalized
            if not HTTP_HEADER_NAME.fullmatch(item) or SECRET_KEY.search(item) or item in builtin
        ]
        if invalid:
            raise ValueError(
                "custom correlation response headers must be safe non-builtin HTTP names: "
                + ", ".join(invalid)
            )
        return normalized

    @field_validator("trusted_origins")
    @classmethod
    def normalize_origins(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(validate_api_trusted_origin(item) for item in value))


class LocalApiService(StrictModel):
    source_directory: str = Field(min_length=1)
    environments: dict[str, LocalApiEnvironment] = Field(min_length=1)


class LocalApiConfig(StrictModel):
    services: dict[str, LocalApiService] = Field(default_factory=dict)


class AgenticQaLocalConfig(StrictModel):
    schema_version: Literal["agentic-qa.local-config.v1"] = "agentic-qa.local-config.v1"
    secrets: SecretProviderDescriptor
    model: LocalModelConfig
    rag: LocalRagConfig
    postgres: LocalPostgresConfig
    test_management: LocalTestManagementConfig
    workspace_defaults: LocalWorkspaceDefaults = Field(default_factory=LocalWorkspaceDefaults)
    runtime: LocalRuntimeConfig = Field(default_factory=LocalRuntimeConfig)
    api: LocalApiConfig = Field(default_factory=LocalApiConfig)
    logs: LocalLogsConfig = Field(default_factory=LocalLogsConfig)


class LocalConfigIssue(StrictModel):
    code: str = Field(min_length=1)
    location: str = Field(min_length=1)
    message: str = Field(min_length=1)
    remediation: str = Field(min_length=1)
    severity: Literal["warning", "error"] = "error"


class LocalConfigCheckResult(StrictModel):
    schema_version: Literal["agentic-qa.harness.local-config-check-result.v1"] = (
        "agentic-qa.harness.local-config-check-result.v1"
    )
    ready: bool
    config_path: str
    issues: list[LocalConfigIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ready(self) -> LocalConfigCheckResult:
        if self.ready != (not any(item.severity == "error" for item in self.issues)):
            raise ValueError("ready must match error issues")
        return self
