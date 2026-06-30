from __future__ import annotations

import re
from pathlib import Path

from runtime.graph.nodes.mvp_context_loader import TASK_API_DISCOVERY_REPORT
from runtime.graph.nodes.mvp_generation import _upsert_artifact
from runtime.graph.state import QAWorkflowState
from runtime.tools.api_discovery_normalizer import load_network_capture, render_api_discovery_report
from runtime.workspace import resolve_prd_path

REQUIRED_DISCOVERY_SECTIONS = [
    "采集来源",
    "接口调用链",
    "业务接口候选清单",
    "请求/响应结构摘要",
    "与 Swagger / Apifox 契约的关系",
    "可转入 api-test-draft 的测试建议",
    "脱敏说明",
    "待确认问题",
]
SECRET_PATTERNS = [
    re.compile(r"Bearer\s+(?!<REDACTED>)[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"(?i)Cookie:\s*(?!<REDACTED>)[^\n|]+"),
    re.compile(
        r"(?i)(access_token|refresh_token|token)\s*[:=]\s*(?!<REDACTED>)[A-Za-z0-9._~+/=-]{12,}"
    ),
]


def api_discovery_report_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    if state.task_type != TASK_API_DISCOVERY_REPORT:
        return state
    state.record_node("api_discovery_report_node")
    if state.errors:
        return state
    capture_path = _find_capture_path(repo_root, state)
    if capture_path is None:
        state.errors.append(
            "未找到 network-capture.har 或 network-capture.json，无法生成接口发现报告。"
        )
        return state
    try:
        result = load_network_capture(capture_path)
    except (OSError, ValueError) as exc:
        state.errors.append(f"抓包文件解析失败: {exc}")
        return state
    artifact = render_api_discovery_report(result, run_id=state.run_id)
    state.draft_artifacts["api_discovery_report"] = artifact
    state.draft_artifact = artifact
    output_path = state.output_paths.get("api_discovery_report")
    if output_path:
        state.output_path = output_path
        _upsert_artifact(
            state,
            name="api_discovery_report",
            artifact_type="api_discovery_report",
            output_path=output_path,
        )
    return state


def api_discovery_quality_check_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    if state.task_type != TASK_API_DISCOVERY_REPORT:
        return state
    state.record_node("api_discovery_quality_check_node")
    if state.errors:
        return state
    artifact = state.draft_artifacts.get("api_discovery_report") or ""
    if not artifact.strip():
        state.quality_errors.append("接口发现报告为空。")
        return state
    for section in REQUIRED_DISCOVERY_SECTIONS:
        if not _has_section(artifact, section):
            state.quality_errors.append(f"接口发现报告缺少章节: {section}")
    if any(pattern.search(artifact) for pattern in SECRET_PATTERNS):
        state.quality_errors.append("接口发现报告疑似包含未脱敏 Authorization / Cookie / token。")
    if "完整接口契约" in artifact and "不是完整接口契约" not in artifact:
        state.quality_errors.append("接口发现报告不允许把抓包结果写成完整接口契约。")
    if "生产环境" in artifact or "线上环境" in artifact:
        state.quality_errors.append("接口发现报告不允许默认生产环境执行。")
    _check_output_path(state, repo_root)
    return state


def _find_capture_path(repo_root: Path, state: QAWorkflowState) -> Path | None:
    prd_path = resolve_prd_path(repo_root, state.prd_path)
    candidates = [
        prd_path / "input/network-capture.har",
        prd_path / "input/network-capture.json",
    ]
    if state.run_id:
        candidates.extend(
            [
                prd_path / "runs" / state.run_id / "network-capture.har",
                prd_path / "runs" / state.run_id / "network-capture.json",
            ]
        )
    return next((path for path in candidates if path.is_file()), None)


def _has_section(markdown: str, section: str) -> bool:
    return bool(re.search(rf"^##\s+\d+\.\s+{re.escape(section)}\s*$", markdown, re.MULTILINE))


def _check_output_path(state: QAWorkflowState, repo_root: Path) -> None:
    output_path = state.output_paths.get("api_discovery_report")
    if not output_path:
        state.quality_errors.append("缺少接口发现报告输出路径。")
        return
    prd_path = resolve_prd_path(repo_root, state.prd_path)
    if not (repo_root / Path(output_path)).resolve().is_relative_to(prd_path.resolve()):
        state.quality_errors.append("接口发现报告输出路径必须位于目标 PRD 工作区内。")
    expected_suffix = "/runs/" + (state.run_id or "runtime") + "/artifact-preview.md"
    if not Path(output_path).as_posix().endswith(expected_suffix):
        state.quality_errors.append(
            "接口发现报告输出路径不符合约定: runs/<run_id>/artifact-preview.md"
        )
