from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from harness.domain.security import (
    contains_likely_secret,
    validate_api_assertion_expected_safety,
    validate_api_request_safety,
    validate_api_trusted_origin,
)

CONTRACT_PREFIX = "agentic-qa.harness"
UTC = timezone.utc
ARTIFACT_TYPES = (
    "requirement_analysis",
    "requirement_delta",
    "impact_analysis",
    "testcases",
    "api_test_draft",
    "ui_test_draft",
    "api_discovery_report",
    "qa_report",
    "execution_report",
    "failure_analysis",
    "bug_draft",
)
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
INVALID_WORKSPACE_CHARS = frozenset('<>:"/\\|?*')


def normalize_workspace_id(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    if normalized == "prd" or normalized.startswith("prd/") or "/prd/" in f"/{normalized}/":
        raise ValueError("旧工作区不受 Harness 支持；请使用 workspaces/<id>")
    if normalized.startswith("workspaces/"):
        normalized = normalized.removeprefix("workspaces/")
    if (
        not normalized
        or "/" in normalized
        or normalized in {".", ".."}
        or len(normalized) > 128
        or normalized.endswith(".")
        or any(character in INVALID_WORKSPACE_CHARS for character in normalized)
        or any(ord(character) < 32 for character in normalized)
        or normalized.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES
    ):
        raise ValueError("workspace 必须是单个安全目录名")
    return normalized


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionProfile(StrictModel):
    schema_version: Literal["agentic-qa.harness.execution-profile.v2"] = (
        "agentic-qa.harness.execution-profile.v2"
    )
    environment: str = Field(default="analysis-only", min_length=1)
    base_url_env: str | None = Field(default=None, pattern=r"^[A-Z_][A-Z0-9_]*$")
    allowed_http_methods: list[str] = Field(default_factory=lambda: ["GET", "HEAD", "OPTIONS"])
    allow_ui_mutations: bool = False
    request_timeout_seconds: int = Field(default=10, ge=1, le=60)

    @field_validator("allowed_http_methods")
    @classmethod
    def normalize_methods(cls, value: list[str]) -> list[str]:
        methods = list(dict.fromkeys(item.strip().upper() for item in value if item.strip()))
        if not methods:
            raise ValueError("allowed_http_methods cannot be empty")
        return methods

    @model_validator(mode="after")
    def validate_environment_safety(self) -> ExecutionProfile:
        segments = set(re.split(r"[^a-z0-9]+", self.environment.strip().lower()))
        if segments & {"prod", "production", "live"}:
            raise ValueError("production-like environments are not supported")
        if self.environment == "analysis-only" and self.allow_ui_mutations:
            raise ValueError("analysis-only cannot allow UI mutations")
        return self


HTTP_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


class ApiTokenInjection(StrictModel):
    location: Literal["header"] = "header"
    name: str = Field(
        default="Authorization",
        pattern=r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$",
    )
    prefix: str = Field(default="Bearer", max_length=32)

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        normalized = value.strip()
        if "\r" in normalized or "\n" in normalized:
            raise ValueError("token prefix cannot contain line breaks")
        return normalized

    @field_validator("name")
    @classmethod
    def reject_transport_headers(cls, value: str) -> str:
        if value.casefold() in {"host", "content-length", "transfer-encoding", "connection"}:
            raise ValueError("token injection cannot target a transport-controlled header")
        return value


class StaticTokenApiAuthentication(StrictModel):
    mode: Literal["static_token"]
    token: SecretStr | None = None
    token_env: str | None = Field(default=None, pattern=r"^[A-Z_][A-Z0-9_]*$")
    injection: ApiTokenInjection = Field(default_factory=ApiTokenInjection)

    @model_validator(mode="after")
    def validate_single_token_source(self) -> StaticTokenApiAuthentication:
        configured = int(self.token is not None) + int(self.token_env is not None)
        if configured != 1:
            raise ValueError(
                "static token authentication requires exactly one of token or token_env"
            )
        if self.token is not None and not self.token.get_secret_value().strip():
            raise ValueError("static token cannot be empty")
        return self


class ApiLoginRequest(StrictModel):
    method: Literal["POST"] = "POST"
    path: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)
    query: Any = Field(default_factory=dict)
    body: Any = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or value.startswith("//")
            or "?" in value
            or "#" in value
            or "\r" in value
            or "\n" in value
        ):
            raise ValueError("API login path must be relative and start with '/'")
        return value

    @field_validator("headers")
    @classmethod
    def reject_transport_headers(cls, value: dict[str, str]) -> dict[str, str]:
        forbidden = {"host", "content-length", "transfer-encoding", "connection"}
        invalid = sorted(
            name
            for name, item in value.items()
            if name.casefold() in forbidden
            or not HTTP_HEADER_NAME.fullmatch(name)
            or "\r" in item
            or "\n" in item
        )
        if invalid:
            raise ValueError(
                "API login request contains invalid or transport-controlled headers: "
                + ", ".join(invalid)
            )
        return value

    @model_validator(mode="after")
    def reject_inline_sensitive_values(self) -> ApiLoginRequest:
        validate_api_request_safety(
            path=self.path,
            headers=self.headers,
            query=self.query,
            body=self.body,
            label="API login request",
            allow_runtime_variables=False,
        )
        return self


class ApiLoginRequestEncryption(StrictModel):
    algorithm: Literal["aes-128-cbc-pkcs7-base64-iv-prefix"]
    key_env: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    fields: list[str] = Field(min_length=1)

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: list[str]) -> list[str]:
        fields = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if not fields or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", item) for item in fields):
            raise ValueError("login encryption fields must be unique root JSON field names")
        return fields


class ApiLoginSuccessCondition(StrictModel):
    json_path: str = Field(pattern=r"^\$(?:\.[A-Za-z_][A-Za-z0-9_-]*)+$")
    expected: bool | int | float | str

    @field_validator("expected")
    @classmethod
    def reject_sensitive_expected(cls, value: bool | int | float | str) -> bool | int | float | str:
        validate_api_assertion_expected_safety(value, label="API login success expected")
        return value


class LoginApiAuthentication(StrictModel):
    mode: Literal["login"]
    request: ApiLoginRequest
    token_json_path: str = Field(pattern=r"^\$(?:\.[A-Za-z_][A-Za-z0-9_-]*)+$")
    expected_status_codes: list[int] = Field(default_factory=lambda: [200], min_length=1)
    injection: ApiTokenInjection = Field(default_factory=ApiTokenInjection)
    request_encryption: ApiLoginRequestEncryption | None = None
    success_condition: ApiLoginSuccessCondition | None = None

    @field_validator("expected_status_codes")
    @classmethod
    def validate_expected_status_codes(cls, value: list[int]) -> list[int]:
        if any(code < 100 or code > 599 for code in value):
            raise ValueError("expected login status codes must be valid HTTP status codes")
        if len(value) != len(set(value)):
            raise ValueError("expected login status codes must be unique")
        return value


ApiAuthentication = Annotated[
    StaticTokenApiAuthentication | LoginApiAuthentication,
    Field(discriminator="mode"),
]


class ApiNamespaceInjection(StrictModel):
    location: Literal["header", "query", "body"]
    name: str = Field(min_length=1, max_length=128)
    prefix: str = Field(default="aqa", min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")

    @model_validator(mode="after")
    def validate_name(self) -> ApiNamespaceInjection:
        if self.location == "header":
            if not re.fullmatch(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", self.name):
                raise ValueError("namespace header name is invalid")
            if re.search(
                r"authorization|cookie|token|secret|password|api[_-]?key",
                self.name,
                re.I,
            ):
                raise ValueError("namespace header name must not be sensitive")
        elif not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", self.name):
            raise ValueError("namespace query/body name must be a root field name")
        return self


class ApiIsolationPolicy(StrictModel):
    mode: Literal["shared", "namespace"] = "shared"
    namespace: ApiNamespaceInjection | None = None

    @model_validator(mode="after")
    def validate_namespace(self) -> ApiIsolationPolicy:
        if self.mode == "namespace" and self.namespace is None:
            raise ValueError("namespace isolation requires an injection declaration")
        if self.mode == "shared" and self.namespace is not None:
            raise ValueError("shared isolation cannot declare namespace injection")
        return self


class ApiOperationPolicy(StrictModel):
    classification: Literal[
        "read_only",
        "mutation_cleanup",
        "mutation_idempotent",
        "mutation_no_cleanup",
        "mutation_manual",
    ]
    idempotency_header: str | None = None
    idempotency_key_prefix: str = Field(
        default="aqa", min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$"
    )

    @model_validator(mode="after")
    def validate_idempotency(self) -> ApiOperationPolicy:
        if self.classification == "mutation_idempotent":
            if self.idempotency_header is None:
                raise ValueError("mutation_idempotent requires idempotency_header")
            if not re.fullmatch(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", self.idempotency_header):
                raise ValueError("idempotency_header is invalid")
            if re.search(
                r"authorization|cookie|token|secret|password|api[_-]?key",
                self.idempotency_header,
                re.I,
            ):
                raise ValueError("idempotency_header must not be sensitive")
        elif self.idempotency_header is not None:
            raise ValueError("idempotency_header is only valid for mutation_idempotent")
        return self


def resolve_api_operation_policy(
    operation_policies: dict[str, ApiOperationPolicy],
    method: str | None,
    path: str | None,
) -> ApiOperationPolicy:
    operation = f"{method} {path}"
    configured = operation_policies.get(operation)
    if configured is not None:
        return configured
    classification = (
        "mutation_cleanup" if method in {"POST", "PUT", "PATCH", "DELETE"} else "read_only"
    )
    return ApiOperationPolicy(classification=classification)


class ExecutionEnvironmentPolicy(StrictModel):
    base_url_env: str | None = Field(default=None, pattern=r"^[A-Z_][A-Z0-9_]*$")
    trusted_origins: list[str] = Field(default_factory=list)
    allowed_http_methods: list[str] = Field(default_factory=lambda: ["GET", "HEAD", "OPTIONS"])
    allow_ui_mutations: bool = False
    max_request_timeout_seconds: int = Field(default=10, ge=1, le=60)
    cleanup_exempt_operations: list[str] = Field(default_factory=list)
    isolation: ApiIsolationPolicy = Field(default_factory=ApiIsolationPolicy)
    operation_policies: dict[str, ApiOperationPolicy] = Field(default_factory=dict)
    api_auth: ApiAuthentication | None = None

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

    @field_validator("operation_policies")
    @classmethod
    def normalize_operation_policies(
        cls, value: dict[str, ApiOperationPolicy]
    ) -> dict[str, ApiOperationPolicy]:
        normalized: dict[str, ApiOperationPolicy] = {}
        for raw_operation, policy in value.items():
            method, separator, path = raw_operation.strip().partition(" ")
            method = method.upper()
            if not separator or method not in {
                "GET",
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
                "HEAD",
                "OPTIONS",
                "TRACE",
            }:
                raise ValueError("operation policies must use canonical METHOD /path keys")
            if not path.startswith("/") or " " in path:
                raise ValueError("operation policy path must be a relative path template")
            canonical = f"{method} {path}"
            if canonical in normalized:
                raise ValueError("operation policy keys must be unique after normalization")
            normalized[canonical] = policy
        return normalized

    @field_validator("trusted_origins")
    @classmethod
    def normalize_trusted_origins(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(validate_api_trusted_origin(item) for item in value))
        return normalized

    @model_validator(mode="after")
    def require_trusted_origin_for_base_url(self) -> ExecutionEnvironmentPolicy:
        if self.base_url_env is not None and not self.trusted_origins:
            raise ValueError("workspace API execution policy requires trusted_origins")
        return self


class ApiScenarioPrepareCommand(StrictModel):
    schema_version: Literal["agentic-qa.harness.api-scenario-prepare-command.v1"] = (
        "agentic-qa.harness.api-scenario-prepare-command.v1"
    )
    source_directory: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    environment: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    execution_policy: ExecutionEnvironmentPolicy | None = None
    workspace_id: str | None = None
    request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    quality_policies: list[str] = Field(default_factory=list)

    @field_validator("workspace_id")
    @classmethod
    def normalize_optional_workspace(cls, value: str | None) -> str | None:
        return normalize_workspace_id(value) if value is not None else None

    @field_validator("goal")
    @classmethod
    def reject_goal_secrets(cls, value: str) -> str:
        if contains_likely_secret(value):
            raise ValueError("goal contains a likely secret; use local configuration instead")
        return value

    @field_validator("environment")
    @classmethod
    def reject_production_environment(cls, value: str) -> str:
        ExecutionProfile(environment=value)
        if value == "analysis-only":
            raise ValueError("API scenario prepare requires an explicit QA environment")
        return value

    @model_validator(mode="after")
    def validate_execution_policy(self) -> ApiScenarioPrepareCommand:
        if self.execution_policy is None:
            return self
        if self.execution_policy.base_url_env is None:
            raise ValueError("API scenario prepare requires execution_policy.base_url_env")
        authentication = self.execution_policy.api_auth
        if isinstance(authentication, StaticTokenApiAuthentication) and authentication.token:
            raise ValueError("API scenario prepare only accepts token_env, never an inline token")
        if len(self.quality_policies) != len(set(self.quality_policies)):
            raise ValueError("quality_policies cannot contain duplicates")
        return self


class StartRunCommand(StrictModel):
    schema_version: Literal["agentic-qa.harness.start-run-command.v2"] = (
        "agentic-qa.harness.start-run-command.v2"
    )
    workspace_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    expected_artifacts: list[str] = Field(default_factory=lambda: ["testcases"])
    execution_profile: ExecutionProfile = Field(default_factory=ExecutionProfile)
    generation_mode: Literal["standard", "api_fast"] = "standard"
    requirement_baseline_run_id: str | None = Field(default=None, min_length=1)

    @field_validator("workspace_id")
    @classmethod
    def reject_legacy_workspace(cls, value: str) -> str:
        return normalize_workspace_id(value)

    @field_validator("goal")
    @classmethod
    def reject_secrets_in_goal(cls, value: str) -> str:
        if contains_likely_secret(value):
            raise ValueError("goal contains a likely secret; use local configuration instead")
        return value

    @field_validator("expected_artifacts")
    @classmethod
    def validate_artifacts(cls, value: list[str]) -> list[str]:
        artifacts = list(dict.fromkeys(value))
        unknown = sorted(set(artifacts) - set(ARTIFACT_TYPES))
        if unknown:
            raise ValueError(f"未知产物类型: {', '.join(unknown)}")
        if not artifacts:
            raise ValueError("expected_artifacts cannot be empty")
        return artifacts

    @model_validator(mode="after")
    def validate_generation_mode(self) -> StartRunCommand:
        if self.generation_mode == "api_fast" and self.expected_artifacts != ["api_test_draft"]:
            raise ValueError("api_fast generation only supports api_test_draft")
        return self


class EvidenceRequirement(StrictModel):
    kind: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required: bool = True


class PlanTask(StrictModel):
    id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)


class QAPlan(StrictModel):
    schema_version: Literal["agentic-qa.harness.qa-plan.v2"] = "agentic-qa.harness.qa-plan.v2"
    tasks: list[PlanTask] = Field(min_length=1)
    revision: int = Field(default=0, ge=0)
    rationale: str = ""

    @model_validator(mode="after")
    def validate_graph(self) -> QAPlan:
        ids = [task.id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("plan task ids must be unique")
        known = set(ids)
        for task in self.tasks:
            missing = set(task.dependencies) - known
            if missing:
                raise ValueError(f"task {task.id} has unknown dependencies: {sorted(missing)}")
            if task.id in task.dependencies:
                raise ValueError(f"task {task.id} cannot depend on itself")
        pending = {task.id: set(task.dependencies) for task in self.tasks}
        while pending:
            ready = {task_id for task_id, deps in pending.items() if not deps}
            if not ready:
                raise ValueError("plan contains a dependency cycle")
            pending = {
                task_id: deps - ready for task_id, deps in pending.items() if task_id not in ready
            }
        return self


class PromptInstructionKind(str, Enum):
    GUIDANCE = "guidance"
    CONTRACT = "contract"
    SAFETY = "safety"


class PromptInstruction(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    kind: PromptInstructionKind
    text: str = Field(min_length=1)
    enforced_by: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_enforcement(self) -> PromptInstruction:
        if self.kind in {PromptInstructionKind.CONTRACT, PromptInstructionKind.SAFETY}:
            if not self.enforced_by:
                raise ValueError(f"{self.kind.value} instruction requires enforced_by")
        if len(self.enforced_by) != len(set(self.enforced_by)):
            raise ValueError("enforced_by entries must be unique")
        allowed_prefixes = ("schema:", "validator:", "allowlist:", "gate:", "repository:")
        invalid = [item for item in self.enforced_by if not item.startswith(allowed_prefixes)]
        if invalid:
            raise ValueError(f"unknown deterministic enforcement references: {invalid}")
        return self


class AgentManifest(StrictModel):
    """Public v2 manifest contract retained for API compatibility; runtime uses v3."""

    schema_version: Literal["agentic-qa.harness.agent-manifest.v2"] = (
        "agentic-qa.harness.agent-manifest.v2"
    )
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    role: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    tool_allowlist: list[str] = Field(default_factory=list)
    input_schema: str = "agentic-qa.harness.agent-input.v2"
    output_schema: str = "agentic-qa.harness.agent-output.v2"
    max_steps: int = Field(default=8, ge=1, le=50)


class SkillManifest(StrictModel):
    """Public v2 manifest contract retained for API compatibility; runtime uses v3."""

    schema_version: Literal["agentic-qa.harness.skill-manifest.v2"] = (
        "agentic-qa.harness.skill-manifest.v2"
    )
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    description: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    references: list[str] = Field(default_factory=list)


class AgentPromptManifest(StrictModel):
    schema_version: Literal["agentic-qa.harness.agent-manifest.v3"] = (
        "agentic-qa.harness.agent-manifest.v3"
    )
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    role: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    responsibilities: list[PromptInstruction] = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    tool_allowlist: list[str] = Field(default_factory=list)
    input_schema: str = "agentic-qa.harness.agent-input.v2"
    output_schema: str = "agentic-qa.harness.agent-output.v2"
    max_steps: int = Field(default=8, ge=1, le=50)

    @model_validator(mode="after")
    def validate_instruction_ids(self) -> AgentPromptManifest:
        ids = [item.id for item in self.responsibilities]
        if len(ids) != len(set(ids)):
            raise ValueError("agent responsibility ids must be unique")
        return self


class SkillPromptManifest(StrictModel):
    schema_version: Literal["agentic-qa.harness.skill-manifest.v3"] = (
        "agentic-qa.harness.skill-manifest.v3"
    )
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    description: str = Field(min_length=1)
    instructions: list[PromptInstruction] = Field(min_length=1)
    knowledge_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_instruction_ids(self) -> SkillPromptManifest:
        ids = [item.id for item in self.instructions]
        if len(ids) != len(set(ids)):
            raise ValueError("skill instruction ids must be unique")
        if len(self.knowledge_refs) != len(set(self.knowledge_refs)):
            raise ValueError("knowledge_refs must be unique")
        return self


class KnowledgeSpec(StrictModel):
    schema_version: Literal["agentic-qa.harness.knowledge-spec.v1"] = (
        "agentic-qa.harness.knowledge-spec.v1"
    )
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    version: str = Field(pattern=r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
    purpose: str = Field(min_length=1)
    applies_to: list[str] = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    procedure: list[str] = Field(min_length=1)
    output_expectations: list[str] = Field(min_length=1)
    evidence_policy: list[str] = Field(min_length=1)
    uncertainty_policy: list[str] = Field(min_length=1)
    prohibited_actions: list[str] = Field(min_length=1)
    deterministic_checks: list[str] = Field(min_length=1)

    @field_validator(
        "applies_to",
        "inputs",
        "procedure",
        "output_expectations",
        "evidence_policy",
        "uncertainty_policy",
        "prohibited_actions",
        "deterministic_checks",
    )
    @classmethod
    def validate_unique_nonempty_items(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("knowledge list entries cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("knowledge list entries must be unique")
        return normalized

    @field_validator("deterministic_checks")
    @classmethod
    def validate_deterministic_checks(cls, value: list[str]) -> list[str]:
        allowed_prefixes = ("schema:", "validator:", "allowlist:", "gate:", "repository:")
        invalid = [item for item in value if not item.startswith(allowed_prefixes)]
        if invalid:
            raise ValueError(f"unknown deterministic checks: {invalid}")
        return value


class PhasePromptManifest(StrictModel):
    schema_version: Literal["agentic-qa.harness.phase-prompt-manifest.v1"] = (
        "agentic-qa.harness.phase-prompt-manifest.v1"
    )
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    version: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    agents: list[str] = Field(min_length=1)
    objective: str = Field(min_length=1)
    instructions: list[PromptInstruction] = Field(min_length=1)
    trusted_input_fields: list[str] = Field(default_factory=list)
    untrusted_input_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_phase(self) -> PhasePromptManifest:
        ids = [item.id for item in self.instructions]
        if len(ids) != len(set(ids)):
            raise ValueError("phase instruction ids must be unique")
        overlap = set(self.trusted_input_fields) & set(self.untrusted_input_fields)
        if overlap:
            raise ValueError(f"phase input fields have conflicting trust levels: {sorted(overlap)}")
        return self


class CompiledPrompt(StrictModel):
    schema_version: Literal["agentic-qa.harness.compiled-prompt.v1"] = (
        "agentic-qa.harness.compiled-prompt.v1"
    )
    phase: str
    template_version: str
    content: str
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reference_versions: dict[str, str] = Field(default_factory=dict)
    trusted_input_fields: list[str] = Field(default_factory=list)
    untrusted_input_fields: list[str] = Field(default_factory=list)


class ToolRisk(str, Enum):
    READ_ONLY = "read_only"
    TEST_MUTATION = "test_mutation"
    ARTIFACT_WRITE = "artifact_write"
    PUBLISH = "publish"


class ToolManifest(StrictModel):
    schema_version: Literal["agentic-qa.harness.tool-manifest.v2"] = (
        "agentic-qa.harness.tool-manifest.v2"
    )
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    provider: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    risk: ToolRisk
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    idempotency: Literal["read", "keyed", "none"]


class ArtifactVariant(str, Enum):
    RAW = "raw"
    NORMALIZED = "normalized"


class ArtifactVersion(StrictModel):
    variant: ArtifactVariant
    path: str
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ArtifactAttachmentRef(StrictModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    media_type: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ArtifactAttachment(ArtifactAttachmentRef):
    path: str


class ArtifactVersionRef(StrictModel):
    artifact: str
    variant: ArtifactVariant
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    assessment_key: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    quality_report_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    attachments: tuple[ArtifactAttachmentRef, ...] = ()


class ApprovedArtifactVersion(ArtifactVersionRef):
    path: str


class ArtifactCandidate(StrictModel):
    artifact: str
    path: str
    media_type: str | None = "text/markdown"
    status: Literal["needs_human_review", "partial", "provenance_incomplete"] = "needs_human_review"
    partial: bool | None = False
    evidence: list[str] | None = Field(default_factory=list)
    provenance_complete: bool = True
    versions: list[ArtifactVersion] = Field(default_factory=list)
    assessment_key: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    quality_report_path: str | None = None
    quality_report_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    generation_report_path: str | None = None
    generation_report_sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    source_bundle_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    policy_versions: dict[str, str] = Field(default_factory=dict)
    attachments: list[ArtifactAttachment] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_quality_flag(cls, value: Any) -> Any:
        if isinstance(value, dict) and "quality_passed" in value:
            value = dict(value)
            value.pop("quality_passed", None)
        return value

    def version_ref(self, variant: ArtifactVariant) -> ArtifactVersionRef:
        version = next((item for item in self.versions if item.variant == variant), None)
        if version is None or self.assessment_key is None or self.quality_report_sha256 is None:
            raise ValueError(f"candidate version 或质量 provenance 不可用: {variant.value}")
        return ArtifactVersionRef(
            artifact=self.artifact,
            variant=variant,
            content_sha256=version.content_sha256,
            assessment_key=self.assessment_key,
            quality_report_sha256=self.quality_report_sha256,
            attachments=tuple(
                ArtifactAttachmentRef(
                    name=item.name,
                    media_type=item.media_type,
                    content_sha256=item.content_sha256,
                )
                for item in self.attachments
            ),
        )


class ApiScenarioSourceFile(StrictModel):
    path: str = Field(min_length=1)
    kind: Literal["openapi", "manual_test_cases", "ignored"]
    case_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class ApiScenarioSourceSummary(StrictModel):
    schema_version: Literal["agentic-qa.harness.api-scenario-source-summary.v1"] = (
        "agentic-qa.harness.api-scenario-source-summary.v1"
    )
    openapi_files: list[ApiScenarioSourceFile]
    manual_case_files: list[ApiScenarioSourceFile]
    ignored_files: list[ApiScenarioSourceFile] = Field(default_factory=list)
    manual_case_ids: list[str]


class ApiScenarioCandidateSummary(StrictModel):
    artifact: Literal["api_test_draft"] = "api_test_draft"
    status: str
    partial: bool
    versions: list[ArtifactVersion]
    candidate_path: str
    quality_report_path: str
    generation_report_path: str | None = None


class ApiScenarioPrepareResult(StrictModel):
    schema_version: Literal["agentic-qa.harness.api-scenario-prepare-result.v1"] = (
        "agentic-qa.harness.api-scenario-prepare-result.v1"
    )
    request_key: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    workspace_id: str
    run_id: str
    status: str
    environment: str
    sources: ApiScenarioSourceSummary
    candidate: ApiScenarioCandidateSummary
    next_action: Literal["human_review_required"]


class BudgetUsage(StrictModel):
    model_calls: int = 0
    tool_calls: int = 0
    replans: int = 0
    elapsed_seconds: float = 0


class HarnessEvent(StrictModel):
    schema_version: Literal["agentic-qa.harness.event.v2"] = "agentic-qa.harness.event.v2"
    sequence: int = Field(ge=1)
    run_id: str
    type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    task_id: str | None = None
    agent: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


RunStatus = Literal[
    "planning",
    "running",
    "needs_human_review",
    "partial",
    "rejected",
    "needs_revision",
    "published",
    "failed",
    "recoverable",
    "on_hold",
]


class RunSnapshot(StrictModel):
    schema_version: Literal["agentic-qa.harness.run-snapshot.v2"] = (
        "agentic-qa.harness.run-snapshot.v2"
    )
    run_id: str
    workspace_id: str
    status: RunStatus
    request: StartRunCommand
    plan: QAPlan | None = None
    completed_tasks: list[str] = Field(default_factory=list)
    pending_tasks: list[str] = Field(default_factory=list)
    candidates: list[ArtifactCandidate] = Field(default_factory=list)
    review_status: dict[str, str] = Field(default_factory=dict)
    delegations: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    model_usage: dict[str, int] = Field(default_factory=dict)
    model_routes: list[dict[str, Any]] = Field(default_factory=list)
    interrupt: dict[str, Any] | None = None
    budget: BudgetUsage = Field(default_factory=BudgetUsage)
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


class ReviewIntent(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REVISE = "revise"
    HOLD = "hold"


class ArtifactDiffEndpoint(str, Enum):
    PUBLISHED = "published"
    RAW = "raw"
    NORMALIZED = "normalized"


class ArtifactDiffResult(StrictModel):
    artifact: str
    before: ArtifactDiffEndpoint
    after: ArtifactDiffEndpoint
    before_sha256: str
    after_sha256: str
    diff: str
    truncated: bool = False


class ReviewDecision(StrictModel):
    schema_version: Literal["agentic-qa.harness.review-decision.v2"] = (
        "agentic-qa.harness.review-decision.v2"
    )
    intent: ReviewIntent
    target_artifact: str | None = None
    reason: str = Field(min_length=1)
    revision_request: str | None = None
    reviewed_by: str = Field(min_length=1)
    versions: list[ArtifactVersionRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_revision(self) -> ReviewDecision:
        if self.intent == ReviewIntent.REVISE and not self.revision_request:
            raise ValueError("revise requires revision_request")
        if self.intent != ReviewIntent.APPROVE and self.versions:
            raise ValueError("versions are only allowed for approve decisions")
        if len({item.artifact for item in self.versions}) != len(self.versions):
            raise ValueError("approve versions must contain each artifact at most once")
        return self


class CreateWorkspaceCommand(StrictModel):
    schema_version: Literal["agentic-qa.harness.create-workspace-command.v2"] = (
        "agentic-qa.harness.create-workspace-command.v2"
    )
    workspace_id: str = Field(min_length=1)
    quality_policies: list[str] = Field(default_factory=list)

    @field_validator("workspace_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return normalize_workspace_id(value)

    @field_validator("quality_policies")
    @classmethod
    def unique_policies(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("quality_policies cannot contain duplicates")
        return value


class RunRef(StrictModel):
    schema_version: Literal["agentic-qa.harness.run-ref.v2"] = "agentic-qa.harness.run-ref.v2"
    workspace_id: str = Field(min_length=1)
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

    @field_validator("workspace_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return normalize_workspace_id(value)


class ExecuteApiCasesCommand(RunRef):
    schema_version: Literal["agentic-qa.harness.execute-api-cases-command.v1"] = (
        "agentic-qa.harness.execute-api-cases-command.v1"
    )
    cases_path: str = "published/api_test_draft/current.yml"
    source_cases_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    execution_profile: ExecutionProfile


class RunApiScenarioCommand(StrictModel):
    schema_version: Literal["agentic-qa.harness.run-api-scenario-command.v1"] = (
        "agentic-qa.harness.run-api-scenario-command.v1"
    )
    workspace_id: str = Field(min_length=1)
    execution_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    environment: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )

    @field_validator("workspace_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return normalize_workspace_id(value)

    @field_validator("environment")
    @classmethod
    def reject_production_environment(cls, value: str) -> str:
        ExecutionProfile(environment=value)
        if value == "analysis-only":
            raise ValueError("API scenario run requires an explicit QA environment")
        return value


class ExportApiPytestCommand(StrictModel):
    schema_version: Literal["agentic-qa.harness.export-api-pytest-command.v1"] = (
        "agentic-qa.harness.export-api-pytest-command.v1"
    )
    workspace_id: str = Field(min_length=1)
    cases_path: str = "published/api_test_draft/current.yml"
    output_path: str = "exports/api_test_draft/test_api_cases.py"
    overwrite: bool = False

    @field_validator("workspace_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return normalize_workspace_id(value)


class ApiPytestExportResult(StrictModel):
    schema_version: Literal["agentic-qa.harness.api-pytest-export-result.v1"] = (
        "agentic-qa.harness.api-pytest-export-result.v1"
    )
    workspace_id: str
    source_cases_path: str
    source_cases_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_path: str
    output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class GetArtifactDiffQuery(RunRef):
    schema_version: Literal["agentic-qa.harness.get-artifact-diff-query.v2"] = (
        "agentic-qa.harness.get-artifact-diff-query.v2"
    )
    artifact: str
    before: ArtifactDiffEndpoint
    after: ArtifactDiffEndpoint


class ResumeRunCommand(RunRef):
    schema_version: Literal["agentic-qa.harness.resume-run-command.v2"] = (
        "agentic-qa.harness.resume-run-command.v2"
    )


class ReviewRunCommand(RunRef):
    schema_version: Literal["agentic-qa.harness.review-run-command.v2"] = (
        "agentic-qa.harness.review-run-command.v2"
    )
    decision: ReviewDecision
