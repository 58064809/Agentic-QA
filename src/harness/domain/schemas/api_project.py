from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from harness.domain.models import (
    ApiLoginSuccessCondition,
    ApiTokenInjection,
    ExecutionEnvironmentPolicy,
    StrictModel,
)
from harness.domain.security import validate_api_trusted_origin

ENV_NAME_PATTERN = r"^[A-Z_][A-Z0-9_]*$"


class ApiLoginEncryption(StrictModel):
    required: bool = False
    status: Literal["pending", "configured"] = "pending"
    algorithm: Literal["aes-128-cbc-pkcs7-base64-iv-prefix"] | None = None
    key_env: str | None = Field(default=None, pattern=ENV_NAME_PATTERN)
    fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_configured_encryption(self) -> ApiLoginEncryption:
        if self.status == "configured" and (
            self.algorithm is None or self.key_env is None or not self.fields
        ):
            raise ValueError("configured encryption requires algorithm, key_env, and fields")
        if len(self.fields) != len(set(self.fields)):
            raise ValueError("encryption fields must be unique")
        if any(not field or not field.replace("-", "_").isidentifier() for field in self.fields):
            raise ValueError("encryption fields must be root JSON field names")
        return self


class ApiPasswordLogin(StrictModel):
    kind: Literal["password"]
    request_path: str = Field(min_length=1)
    username_env: str = Field(pattern=ENV_NAME_PATTERN)
    password_env: str = Field(pattern=ENV_NAME_PATTERN)
    token_json_path: str = Field(pattern=r"^\$(?:\.[A-Za-z_][A-Za-z0-9_-]*)+$")
    expected_status_codes: list[int] = Field(default_factory=lambda: [200], min_length=1)
    request_headers: dict[str, str] = Field(default_factory=dict)
    injection: ApiTokenInjection = Field(default_factory=ApiTokenInjection)
    encryption: ApiLoginEncryption = Field(default_factory=ApiLoginEncryption)
    success_condition: ApiLoginSuccessCondition | None = None


class ApiSmsLogin(StrictModel):
    kind: Literal["sms"]
    request_path: str = Field(min_length=1)
    tel_code_env: str = Field(pattern=ENV_NAME_PATTERN)
    phone_env: str = Field(pattern=ENV_NAME_PATTERN)
    sms_code_env: str = Field(pattern=ENV_NAME_PATTERN)
    token_json_path: str = Field(pattern=r"^\$(?:\.[A-Za-z_][A-Za-z0-9_-]*)+$")
    expected_status_codes: list[int] = Field(default_factory=lambda: [200], min_length=1)
    request_headers: dict[str, str] = Field(default_factory=dict)
    null_body_fields: list[str] = Field(default_factory=list)
    injection: ApiTokenInjection = Field(default_factory=ApiTokenInjection)
    encryption: ApiLoginEncryption = Field(default_factory=ApiLoginEncryption)
    success_condition: ApiLoginSuccessCondition | None = None

    @field_validator("null_body_fields")
    @classmethod
    def validate_null_body_fields(cls, value: list[str]) -> list[str]:
        fields = list(dict.fromkeys(field.strip() for field in value if field.strip()))
        reserved = {"telCode", "phone", "smsCode"}
        if any(not field.replace("-", "_").isidentifier() for field in fields):
            raise ValueError("null_body_fields must contain root JSON field names")
        if reserved & set(fields):
            raise ValueError("null_body_fields cannot replace SMS credential fields")
        return fields


class ApiStaticTokenLogin(StrictModel):
    kind: Literal["static_token"]
    token_env: str = Field(pattern=ENV_NAME_PATTERN)
    injection: ApiTokenInjection = Field(default_factory=ApiTokenInjection)


ApiProjectLogin = Annotated[
    ApiPasswordLogin | ApiSmsLogin | ApiStaticTokenLogin,
    Field(discriminator="kind"),
]


class ApiProjectAuthentication(StrictModel):
    login: ApiProjectLogin | None = None
    fallback_token_env: str | None = Field(default=None, pattern=ENV_NAME_PATTERN)
    fallback_injection: ApiTokenInjection | None = None

    @model_validator(mode="after")
    def require_authentication_source(self) -> ApiProjectAuthentication:
        if self.login is None and self.fallback_token_env is None:
            raise ValueError("auth requires login or fallback_token_env")
        return self


class ApiProjectEnvironment(StrictModel):
    base_url_env: str = Field(pattern=ENV_NAME_PATTERN)
    trusted_origins: list[str] = Field(min_length=1)
    allowed_http_methods: list[str] = Field(min_length=1)
    max_request_timeout_seconds: int = Field(default=10, ge=1, le=60)
    auth: ApiProjectAuthentication | None = None

    @field_validator("allowed_http_methods")
    @classmethod
    def normalize_methods(cls, value: list[str]) -> list[str]:
        methods = list(dict.fromkeys(item.strip().upper() for item in value if item.strip()))
        if not methods:
            raise ValueError("allowed_http_methods cannot be empty")
        return methods

    @field_validator("trusted_origins")
    @classmethod
    def normalize_origins(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(validate_api_trusted_origin(item) for item in value))


class ApiProjectConfig(StrictModel):
    schema_version: Literal["agentic-qa.api-project.v1"] = "agentic-qa.api-project.v1"
    service: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    environments: dict[str, ApiProjectEnvironment] = Field(min_length=1)

    @field_validator("environments")
    @classmethod
    def validate_environment_names(
        cls, value: dict[str, ApiProjectEnvironment]
    ) -> dict[str, ApiProjectEnvironment]:
        invalid = sorted(
            name
            for name in value
            if not name
            or len(name) > 128
            or not name[0].isalnum()
            or any(character not in "._-" and not character.isalnum() for character in name)
        )
        if invalid:
            raise ValueError(f"invalid environment names: {invalid}")
        return value


class ApiProjectIssue(StrictModel):
    code: str = Field(min_length=1)
    location: str = Field(min_length=1)
    env_names: list[str] = Field(default_factory=list)
    message: str = Field(min_length=1)
    remediation: str = Field(min_length=1)


class ApiProjectCheckCommand(StrictModel):
    source_directory: str = Field(min_length=1)
    environment: str = Field(min_length=1, max_length=128)
    execution_policy: ExecutionEnvironmentPolicy | None = None


class ApiProjectCheckResult(StrictModel):
    schema_version: Literal["agentic-qa.harness.api-project-check-result.v1"] = (
        "agentic-qa.harness.api-project-check-result.v1"
    )
    ready: bool
    service: str | None = None
    environment: str
    config_path: str
    selected_authentication: Literal["password", "sms", "static_token"] | None = None
    structural_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    issues: list[ApiProjectIssue] = Field(default_factory=list)
    execution_policy: ExecutionEnvironmentPolicy | None = None

    @model_validator(mode="after")
    def validate_ready_state(self) -> ApiProjectCheckResult:
        if self.ready != (not self.issues and self.execution_policy is not None):
            raise ValueError("ready must match issues and execution_policy")
        return self
