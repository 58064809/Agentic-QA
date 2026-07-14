"""CLI: PRD 路径、run_id、产物关键字等解析工具。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from runtime.workspace import ARTIFACT_SPECS, PRDWorkspace, read_yaml_mapping

# ── 正则与常量 ────────────────────────────────────────────────

PRD_WORKSPACE_PATH_RE = re.compile(
    r"""
    (?:
        [a-zA-Z]:\\(?:[^\s\\"']+\\)*prd\\[^\s\\"']+
        |
        prd[/\\][^\s\\"']+
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

API_DOC_PATH_RE = re.compile(
    r"""
    (?:
        [a-zA-Z]:\\(?:[^\s\\"']+\\)*[^\s\\"']+\.(?:json|ya?ml)
        |
        (?:\.?\.?[/\\])?(?:[^\s\\"']+[/\\])*[^\s\\"']+\.(?:json|ya?ml)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

NETWORK_CAPTURE_PATH_RE = re.compile(
    r"""
    (?:
        [a-zA-Z]:\\(?:[^\s\\"']+\\)*[^\s\\"']+\.(?:har|json)
        |
        (?:\.?\.?[/\\])?(?:[^\s\\"']+[/\\])*[^\s\\"']+\.(?:har|json)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

RUN_ID_RE = re.compile(r"run-\d{8}-\d{6}-[a-z0-9]+|runtime", re.IGNORECASE)

PROMOTE_KEYWORDS = ("发布正式产物", "发布产物", "正式发布", "通过并发布", "发布吧", "promote")
APPROVE_KEYWORDS = ("通过", "确认", "approved", "confirmed", "approve")

PROMOTE_KEYWORDS = PROMOTE_KEYWORDS + (
    "发布正式产物",
    "发布产物",
    "正式发布",
    "通过并发布",
    "发布",
)
APPROVE_KEYWORDS = APPROVE_KEYWORDS + (
    "通过",
    "确认",
    "没问题",
    "沒問題",
    "ok",
)
NO_PUBLISH_KEYWORDS = (
    "不要发布",
    "先不发布",
    "暂不发布",
    "不发布",
    "只确认",
    "先确认",
    "通过但不发布",
    "只确认不发布",
)

ARTIFACT_ALIASES: dict[str, tuple[str, ...]] = {
    "requirement_analysis": ("requirement_analysis", "requirement-analysis", "需求分析"),
    "testcases": ("testcases", "testcase", "test-cases", "测试用例", "用例"),
    "api_test_draft": (
        "api_test_draft",
        "api-test-draft",
        "接口测试草稿",
        "接口自动化草稿",
        "RAG 自动化用例",
        "RAG 接口自动化",
        "YAML 接口自动化用例",
        "api-test-cases.yml",
        "接口测试",
        "pytest requests",
    ),
    "ui_test_draft": (
        "ui_test_draft",
        "ui-test-draft",
        "UI 自动化草稿",
        "Playwright 测试草稿",
        "H5 自动化测试",
        "后台页面自动化测试",
        "Android 自动化",
        "安卓自动化",
        "模拟器",
        "APK",
        "appPackage",
        "appActivity",
        "UiAutomator2",
    ),
    "api_discovery_report": (
        "api_discovery_report",
        "api-discovery-report",
        "接口发现报告",
        "抓包",
        "network-capture",
        "接口调用链",
    ),
    "qa_report": ("qa_report", "qa-report", "QA报告", "qa report"),
}


def _supported_artifact_keys(keys: list[str]) -> list[str]:
    return [key for key in dict.fromkeys(keys) if key in ARTIFACT_SPECS]


HELP_TEXT = """用法:
    agentic-qa "你的自然语言命令"
    agentic-qa rag status
    agentic-qa rag build
    agentic-qa rag search "边界值 活动玩法"
    agentic-qa resume <run_id> "测试用例通过，发布正式产物"
    agentic-qa promote prd/sample-login-requirement [run_id] [artifact]

示例:
    agentic-qa "帮我分析登录需求 D:\\需求\\登录.md"
    agentic-qa "分析 prd/sample-login-requirement 并生成测试用例"
    agentic-qa "基于 prd/sample-login-requirement 生成接口测试草稿"
    agentic-qa "测试用例通过，发布正式产物 prd/sample-login-requirement"
    agentic-qa "处理这个飞书链接 https://xxx.feishu.cn/docx/123"
"""


# ── 工具函数 ──────────────────────────────────────────────────


def _extract_prd_workspace_path(user_input: str) -> str | None:
    capture_path = _extract_network_capture_path(user_input)
    if capture_path:
        prd_root = _prd_workspace_from_capture_path(capture_path)
        if prd_root:
            return prd_root
    match = PRD_WORKSPACE_PATH_RE.search(user_input)
    if not match:
        return None
    return match.group(0).strip().rstrip("，。；,;.)>")


def _extract_network_capture_path(user_input: str) -> str | None:
    for match in NETWORK_CAPTURE_PATH_RE.finditer(user_input):
        value = match.group(0).strip().rstrip("，。；,;.)>")
        normalized = value.replace("\\", "/").lower()
        filename = normalized.rsplit("/", 1)[-1]
        if filename in {"network-capture.har", "network-capture.json"} or filename.endswith(".har"):
            return value
    return None


def _prd_workspace_from_capture_path(value: str) -> str | None:
    parts = [part for part in re.split(r"[/\\]+", value.strip()) if part]
    lowered = [part.lower() for part in parts]
    for index, part in enumerate(lowered):
        if part != "prd" or index + 2 >= len(parts):
            continue
        if lowered[index + 2] == "input":
            return "/".join(parts[index : index + 2])
    return None


def _extract_api_doc_path(user_input: str) -> str | None:
    for match in API_DOC_PATH_RE.finditer(user_input):
        value = match.group(0).strip().rstrip("，。；,;.)>")
        lowered = value.lower().replace("\\", "/")
        if "/prd/" in lowered or lowered.startswith("prd/"):
            continue
        return value
    return None


def _extract_run_id(value: str) -> str | None:
    match = RUN_ID_RE.search(value)
    return match.group(0) if match else None


def _explicit_artifact_keys_from_text(value: str) -> list[str]:
    normalized_value = value.lower()
    keys = [
        key
        for key, aliases in ARTIFACT_ALIASES.items()
        if any(alias.lower() in normalized_value for alias in aliases)
    ]
    # 中文字符回退
    is_api_test_text = (
        "接口测试" in value or "接口自动化" in value or "api-test" in normalized_value
    )
    if not is_api_test_text and (
        "测试" in value or "用例" in value or "娴嬭瘯" in value or "鐢ㄤ緥" in value
    ):
        keys.append("testcases")
    if is_api_test_text:
        keys.append("api_test_draft")
    if any(
        keyword in value
        for keyword in (
            "UI 自动化",
            "Playwright",
            "H5 自动化",
            "后台页面自动化",
            "Android",
            "安卓",
            "模拟器",
            "APK",
            "appPackage",
            "appActivity",
            "UiAutomator2",
        )
    ):
        keys.append("ui_test_draft")
    if any(keyword in value for keyword in ("接口发现", "抓包", "接口调用链", "network-capture")):
        keys.append("api_discovery_report")
    if ("需求" in value and "分析" in value) or ("闇€姹" in value and "鍒嗘瀽" in value):
        keys.append("requirement_analysis")
    keys = list(dict.fromkeys(keys))
    return keys


def _publish_all_requested(value: str) -> bool:
    return any(
        keyword in value
        for keyword in (
            "全部",
            "都通过",
            "全部通过",
            "全部发布",
            "都发布",
            "全都发布",
            "all",
        )
    )


def _artifact_keys_from_recorded_run(repo_root: Path, run_id: str | None) -> list[str]:
    if not run_id:
        return []
    result = _read_recorded_run_result(repo_root, run_id)
    output_paths = result.get("output_paths")
    if isinstance(output_paths, dict) and output_paths:
        keys = _supported_artifact_keys([str(key) for key in output_paths])
        if keys:
            return keys
    draft_artifacts = result.get("draft_artifacts")
    if isinstance(draft_artifacts, dict) and draft_artifacts:
        keys = _supported_artifact_keys([str(key) for key in draft_artifacts])
        if keys:
            return keys
    artifacts = result.get("artifacts")
    if isinstance(artifacts, list):
        keys = [
            str(item.get("name"))
            for item in artifacts
            if isinstance(item, dict) and item.get("name")
        ]
        keys = _supported_artifact_keys(keys)
        if keys:
            return keys
    return []


def _clarify_multi_artifact_message(artifact_keys: list[str]) -> str:
    readable = "、".join(artifact_keys)
    return (
        f"检测到本次 run 包含多个候选产物：{readable}。\n"
        "请明确：\n"
        "1. 只发布测试用例\n"
        "2. 只发布需求分析\n"
        "3. 全部发布"
    )


def _task_type_from_artifact_keys(keys: list[str]) -> str:
    normalized = set(keys)
    if normalized == {"requirement_analysis"}:
        return "analysis"
    if normalized == {"testcases"}:
        return "testcase_generation"
    if normalized == {"api_test_draft"}:
        return "api_test_draft"
    if normalized == {"ui_test_draft"}:
        return "ui_test_draft"
    if normalized == {"api_discovery_report"}:
        return "api_discovery_report"
    if normalized == {"qa_report"}:
        return "qa_report"
    return "analysis_and_testcases"


def _is_promote_request(user_input: str) -> bool:
    normalized = user_input.lower()
    return any(keyword.lower() in normalized for keyword in APPROVE_KEYWORDS) or (
        any(keyword.lower() in normalized for keyword in PROMOTE_KEYWORDS)
        and not _approve_without_publish_requested(user_input)
    )


def _approve_without_publish_requested(user_input: str) -> bool:
    return any(keyword in user_input for keyword in NO_PUBLISH_KEYWORDS)


def _looks_like_markdown_requirement(text: str) -> bool:
    """Heuristic: if input looks like a markdown requirement (has headers), treat as inline."""
    return bool(re.search(r"^#{1,3}\s", text, re.MULTILINE))


def _read_recorded_run_result(repo_root: Path, run_id: str) -> dict[str, object]:
    state_path = repo_root / ".runtime" / "runs" / run_id / "run-state.json"
    if not state_path.is_file():
        return {}
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def _read_latest_run_id(workspace: PRDWorkspace) -> str | None:
    latest_path = workspace.runs_dir / "latest.yml"
    if not latest_path.is_file():
        return None
    latest = read_yaml_mapping(latest_path)
    run_id = latest.get("run_id")
    return str(run_id) if run_id else None


def _latest_recorded_run_for_prd(
    repo_root: Path,
    prd_rel: str,
    *,
    run_status: str | None = None,
    review_status: str | None = None,
) -> str | None:
    runs_root = repo_root / ".runtime" / "runs"
    if not runs_root.is_dir():
        return None
    candidates: list[tuple[float, str]] = []
    for state_path in runs_root.glob("*/run-state.json"):
        result = _read_recorded_run_result(repo_root, state_path.parent.name)
        if result.get("prd_path") != prd_rel:
            continue
        if run_status and result.get("run_status") != run_status:
            continue
        if review_status and result.get("review_status") != review_status:
            continue
        candidates.append((state_path.stat().st_mtime, state_path.parent.name))
    if not candidates:
        return None
    return max(candidates)[1]


def _latest_run_id_for_prd(repo_root: Path, prd_rel: str) -> str | None:
    workspace = PRDWorkspace(repo_root / prd_rel)
    return _read_latest_run_id(workspace) or _latest_recorded_run_for_prd(repo_root, prd_rel)


def _is_recorded_run_interrupted(repo_root: Path, run_id: str) -> bool:
    result = _read_recorded_run_result(repo_root, run_id)
    return result.get("run_status") == "interrupted" or (
        result.get("review_status") == "needs_human_review"
        and result.get("next_action") == "wait_for_review"
    )
