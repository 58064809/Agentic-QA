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
        if (
            isinstance(value, Mapping)
            and isinstance(merged.get(key), dict)
        ):
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
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return []


@dataclass(frozen=True)
class LLMConfig:
    """LLM 调用配置。"""

    enabled: bool = True
    semantic_router_enabled: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> LLMConfig:
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", True)),
            semantic_router_enabled=bool(data.get("semantic_router_enabled", True)),
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
            str(key): bool(value)
            for key, value in dict(data.get("use_llm") or {}).items()
        }
        return cls(
            enable_human_checkpoint=bool(data.get("enable_human_checkpoint", True)),
            default_checkpoint_node=str(
                data.get("default_checkpoint_node", "requirement_analysis")
            ),
            intent_workflow_files=intent_workflow_files,
            default_workflow_files=_string_list(data.get("default_workflow_files")),
            intent_context_files=intent_context_files,
            default_context_files=_string_list(data.get("default_context_files")),
            mvp_analysis_workflow_files=_string_list(
                data.get("mvp_analysis_workflow_files")
            ),
            mvp_testcase_workflow_files=_string_list(
                data.get("mvp_testcase_workflow_files")
            ),
            use_llm=use_llm,
        )

    def use_llm_for(self, task_name: str, *, default: bool = True) -> bool:
        return self.use_llm.get(task_name, default)


@dataclass(frozen=True)
class AppConfig:
    """统一应用配置。"""

    raw: dict[str, Any] = field(default_factory=dict)
    llm: LLMConfig = field(default_factory=LLMConfig)
    workflow: WorkflowConfig = field(default_factory=WorkflowConfig)

    @property
    def rag(self) -> dict[str, Any]:
        raw_rag = self.raw.get("rag") or {}
        return dict(raw_rag) if isinstance(raw_rag, dict) else {}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> AppConfig:
        raw = dict(data or {})
        return cls(
            raw=raw,
            llm=LLMConfig.from_dict(raw.get("llm")),
            workflow=WorkflowConfig.from_dict(raw.get("workflow")),
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
