"""Runtime 统一配置层。

配置文件只承载可提交或本地私有的运行参数；密钥仍只从环境变量读取。
加载顺序为 defaults -> configs/config.yaml -> configs/local.yaml -> configs/private.yaml。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_FILES = (
    "configs/config.yaml",
    "configs/local.yaml",
    "configs/private.yaml",
)


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"配置文件必须是 YAML mapping: {path.as_posix()}")
    return raw


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [str(item) for item in value if str(item).strip()]
    return []


def _bool_value(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


def _int_value(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class ProjectConfig:
    """项目基础信息。"""

    name: str = "agentic-qa"
    env: str = "dev"
    profile: str = "default"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> ProjectConfig:
        data = data or {}
        return cls(
            name=str(data.get("name", "agentic-qa")),
            env=str(data.get("env", "dev")),
            profile=str(data.get("profile", "default")),
        )


@dataclass(frozen=True)
class InputConfig:
    """输入来源能力开关。"""

    support_feishu_doc: bool = True
    support_markdown: bool = True
    max_file_chars: int = 200_000

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> InputConfig:
        data = data or {}
        return cls(
            support_feishu_doc=_bool_value(data.get("support_feishu_doc"), default=True),
            support_markdown=_bool_value(data.get("support_markdown"), default=True),
            max_file_chars=_int_value(data.get("max_file_chars"), default=200_000),
        )


@dataclass(frozen=True)
class LLMConfig:
    """LLM 调用配置。"""

    enabled: bool = True
    semantic_router_enabled: bool = True
    provider: str = "deepseek"
    api_key_env: str = "DEEPSEEK_API_KEY"
    base_url_env: str = "DEEPSEEK_BASE_URL"
    model_env: str = "DEEPSEEK_MODEL"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    enable_chat_fallback: bool = True
    max_input_chars: int = 32000

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> LLMConfig:
        data = data or {}
        return cls(
            enabled=_bool_value(data.get("enabled"), default=True),
            semantic_router_enabled=_bool_value(
                data.get("semantic_router_enabled"),
                default=True,
            ),
            provider=str(data.get("provider", "deepseek")),
            api_key_env=str(data.get("api_key_env", "DEEPSEEK_API_KEY")),
            base_url_env=str(data.get("base_url_env", "DEEPSEEK_BASE_URL")),
            model_env=str(data.get("model_env", "DEEPSEEK_MODEL")),
            base_url=str(data.get("base_url", "https://api.deepseek.com")),
            model=str(data.get("model", "deepseek-v4-flash")),
            enable_chat_fallback=_bool_value(
                data.get("enable_chat_fallback"),
                default=True,
            ),
            max_input_chars=_int_value(data.get("max_input_chars"), default=32000),
        )


@dataclass(frozen=True)
class WorkflowConfig:
    """工作流和上下文文件配置。"""

    enable_human_checkpoint: bool = True
    default_checkpoint_node: str = "requirement_analysis"
    intent_workflow_files: dict[str, list[str]] = field(default_factory=dict)
    default_workflow_files: list[str] = field(default_factory=list)
    intent_context_files: dict[str, list[str]] = field(default_factory=dict)
    default_context_files: list[str] = field(default_factory=list)
    mvp_analysis_workflow_files: list[str] = field(default_factory=list)
    mvp_testcase_workflow_files: list[str] = field(default_factory=list)
    use_llm: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> WorkflowConfig:
        data = data or {}
        intent_workflow_files = {
            str(key): _string_list(value)
            for key, value in dict(data.get("intent_workflow_files") or {}).items()
        }
        intent_context_files = {
            str(key): _string_list(value)
            for key, value in dict(data.get("intent_context_files") or {}).items()
        }
        use_llm = {
            str(key): _bool_value(value, default=True)
            for key, value in dict(data.get("use_llm") or {}).items()
        }
        return cls(
            enable_human_checkpoint=_bool_value(
                data.get("enable_human_checkpoint"),
                default=True,
            ),
            default_checkpoint_node=str(
                data.get("default_checkpoint_node", "requirement_analysis")
            ),
            intent_workflow_files=intent_workflow_files,
            default_workflow_files=_string_list(data.get("default_workflow_files")),
            intent_context_files=intent_context_files,
            default_context_files=_string_list(data.get("default_context_files")),
            mvp_analysis_workflow_files=_string_list(data.get("mvp_analysis_workflow_files")),
            mvp_testcase_workflow_files=_string_list(data.get("mvp_testcase_workflow_files")),
            use_llm=use_llm,
        )

    def use_llm_for(self, task_name: str, *, default: bool = True) -> bool:
        return self.use_llm.get(task_name, default)


@dataclass(frozen=True)
class WorkspaceConfig:
    """需求工作区路径和运行记录位置。"""

    prd_root: str = "prd"
    runtime_root: str = ".runtime"
    runs_dir_name: str = "runs"
    artifacts_dir_name: str = "artifacts"
    reviews_dir_name: str = "reviews"
    metadata_file: str = "metadata.yml"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> WorkspaceConfig:
        data = data or {}
        return cls(
            prd_root=str(data.get("prd_root", "prd")),
            runtime_root=str(data.get("runtime_root", ".runtime")),
            runs_dir_name=str(data.get("runs_dir_name", "runs")),
            artifacts_dir_name=str(data.get("artifacts_dir_name", "artifacts")),
            reviews_dir_name=str(data.get("reviews_dir_name", "reviews")),
            metadata_file=str(data.get("metadata_file", "metadata.yml")),
        )


@dataclass(frozen=True)
class OutputConfig:
    """输出格式和写入策略开关。"""

    markdown: bool = True
    yaml: bool = True
    json: bool = True
    write_artifact_preview: bool = True
    require_review_gate: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> OutputConfig:
        data = data or {}
        return cls(
            markdown=_bool_value(data.get("markdown"), default=True),
            yaml=_bool_value(data.get("yaml"), default=True),
            json=_bool_value(data.get("json"), default=True),
            write_artifact_preview=_bool_value(
                data.get("write_artifact_preview"),
                default=True,
            ),
            require_review_gate=_bool_value(
                data.get("require_review_gate"),
                default=True,
            ),
        )


@dataclass(frozen=True)
class RuntimeConfig:
    """Runtime 执行策略。"""

    default_entry: str = "cli"
    record_runs: bool = True
    idempotency_enabled: bool = True
    fail_fast_required_nodes: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> RuntimeConfig:
        data = data or {}
        return cls(
            default_entry=str(data.get("default_entry", "cli")),
            record_runs=_bool_value(data.get("record_runs"), default=True),
            idempotency_enabled=_bool_value(
                data.get("idempotency_enabled"),
                default=True,
            ),
            fail_fast_required_nodes=_bool_value(
                data.get("fail_fast_required_nodes"),
                default=True,
            ),
        )


@dataclass(frozen=True)
class EntryConfig:
    """协作入口开关。"""

    cli_enabled: bool = True
    api_enabled: bool = False
    chat_enabled: bool = True
    bot_enabled: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> EntryConfig:
        data = data or {}
        return cls(
            cli_enabled=_bool_value(data.get("cli_enabled"), default=True),
            api_enabled=_bool_value(data.get("api_enabled"), default=False),
            chat_enabled=_bool_value(data.get("chat_enabled"), default=True),
            bot_enabled=_bool_value(data.get("bot_enabled"), default=False),
        )


@dataclass(frozen=True)
class LoggingConfig:
    """日志配置，不包含密钥。"""

    level: str = "INFO"
    dir: str = "logs"
    redact_secrets: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> LoggingConfig:
        data = data or {}
        return cls(
            level=str(data.get("level", "INFO")).upper(),
            dir=str(data.get("dir", "logs")),
            redact_secrets=_bool_value(data.get("redact_secrets"), default=True),
        )


@dataclass(frozen=True)
class AppConfig:
    """统一应用配置。"""

    raw: dict[str, Any] = field(default_factory=dict)
    project: ProjectConfig = field(default_factory=ProjectConfig)
    input: InputConfig = field(default_factory=InputConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    workflow: WorkflowConfig = field(default_factory=WorkflowConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    entries: EntryConfig = field(default_factory=EntryConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def rag(self):
        """Lazy-imported typed RAG configuration."""
        from rag.config import RagConfig

        raw_rag = self.raw.get("rag") or {}
        return RagConfig.from_app_config(dict(raw_rag) if isinstance(raw_rag, dict) else {})

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> AppConfig:
        raw = dict(data or {})
        return cls(
            raw=raw,
            project=ProjectConfig.from_dict(raw.get("app")),
            input=InputConfig.from_dict(raw.get("input")),
            llm=LLMConfig.from_dict(raw.get("llm")),
            workflow=WorkflowConfig.from_dict(raw.get("workflow")),
            workspace=WorkspaceConfig.from_dict(raw.get("workspace")),
            output=OutputConfig.from_dict(raw.get("output")),
            runtime=RuntimeConfig.from_dict(raw.get("runtime")),
            entries=EntryConfig.from_dict(raw.get("entries")),
            logging=LoggingConfig.from_dict(raw.get("logging")),
            profiles={
                str(key): _mapping(value) for key, value in _mapping(raw.get("profiles")).items()
            },
        )


def load_app_config(
    repo_root: Path | None = None,
    *,
    config_files: tuple[str, ...] = DEFAULT_CONFIG_FILES,
) -> AppConfig:
    """加载统一配置。

    `configs/config.yaml` 不提交真实密钥；密钥引用只通过 `*_api_key_env`
    或现有环境变量完成。
    """
    root = (repo_root or Path.cwd()).resolve()
    merged: dict[str, Any] = {}
    for relative_path in config_files:
        merged = _deep_merge(merged, _read_yaml_mapping(root / relative_path))
    return AppConfig.from_dict(merged)
