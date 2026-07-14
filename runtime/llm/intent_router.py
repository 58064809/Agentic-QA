"""LLM 语义路由：从自然语言提取当前 Runtime 支持的意图和文档来源。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from runtime.llm.config import OpenAICompatibleConfig
from runtime.llm.openai_compatible import OpenAICompatibleAdapter

SUPPORTED_INTENTS: dict[str, str] = {
    "mvp": "需求分析 + 测试用例生成",
    "requirement_analysis": "需求分析",
    "testcase_generation": "测试用例生成",
    "api_test_draft": "API 接口测试草稿生成",
    "rag_automation_case_generation": "RAG 接口自动化 YAML 用例生成",
    "ui_test_draft": "UI 自动化测试草稿生成",
    "api_discovery_report": "接口发现报告生成",
    "qa_report": "QA 报告生成",
    "resume": "继续当前会话",
}
CONTROL_INTENTS = {"reset"}
ROUTER_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "semantic-router-prompt.md"

LOCAL_PATH_RE = re.compile(
    r"""
    [a-zA-Z]:\\(?:[^\\"']+\\)*[^\\"']+\.(?:md|pdf|docx|txt|html|xlsx)
    |
    /(?:[^/"']+/)*[^/"']+\.(?:md|pdf|docx|txt|html|xlsx)
    """,
    re.IGNORECASE | re.VERBOSE,
)
PRD_WORKSPACE_RE = re.compile(
    r"""
    (?:
        [a-zA-Z]:\\(?:[^\\"']+\\)*prd\\[^\s\\"']+
        |
        prd[/\\][^\s\\"']+
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
URL_RE = re.compile(
    r"https?://[^\s\"'<>]+(?:feishu|lark|feishu\.cn)[^\s\"'<>]*",
    re.IGNORECASE,
)
RESET_KEYWORDS = ("重新开始", "重置", "从头开始", "new session", "reset", "新会话")


@dataclass
class IntentRouteResult:
    intent: str = ""
    prd_path: str | None = None
    url: str | None = None
    summary: str = ""
    errors: list[str] = field(default_factory=list)
    raw_response: str = ""

    @property
    def is_valid(self) -> bool:
        return bool(self.intent) and not self.errors

    @property
    def is_reset(self) -> bool:
        return self.intent == "reset"


def _router_system_prompt() -> str:
    try:
        template = ROUTER_PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"无法读取语义路由 Prompt: {ROUTER_PROMPT_PATH}") from exc
    intent_lines = "\n".join(f"- `{name}`：{description}" for name, description in SUPPORTED_INTENTS.items())
    return template.replace("{{SUPPORTED_INTENTS}}", intent_lines)


def _extract_paths_fallback(user_input: str) -> tuple[str | None, str | None]:
    """确定性提取 PRD/本地文件路径和飞书 URL。"""
    from runtime.cli.parser import _extract_prd_workspace_path

    prd_path = _extract_prd_workspace_path(user_input)
    if not prd_path:
        match = LOCAL_PATH_RE.search(user_input)
        if match:
            prd_path = match.group(0).strip()

    url = None
    match = URL_RE.search(user_input)
    if match:
        url = match.group(0).strip().rstrip(".)>")
    return prd_path, url


def _infer_intent_fallback(user_input: str) -> str:
    """LLM 不可用时，只路由到当前 Registry 支持的意图。"""
    lowered = user_input.lower()
    has_analysis = any(keyword in user_input for keyword in ("分析", "拆解", "需求分析"))
    has_testcases = any(
        keyword in user_input for keyword in ("测试用例", "用例", "testcase", "test case")
    )

    if any(
        keyword in user_input
        for keyword in (
            "RAG 自动化用例",
            "rag 自动化用例",
            "RAG 接口自动化",
            "rag 接口自动化",
            "YAML 接口自动化用例",
            "yaml 接口自动化用例",
            "api-test-cases.yml",
        )
    ):
        return "rag_automation_case_generation"
    if has_analysis and has_testcases:
        return "mvp"
    if has_analysis:
        return "requirement_analysis"
    if has_testcases:
        return "testcase_generation"
    if any(
        keyword in user_input
        for keyword in ("接口发现", "抓包", "network-capture", "接口调用链", "HAR")
    ):
        return "api_discovery_report"
    if any(
        keyword in user_input
        for keyword in (
            "UI 自动化",
            "Playwright",
            "H5 自动化",
            "后台页面自动化",
            "UI 自动化脚本",
            "Android",
            "安卓",
            "模拟器",
            "APK",
            "appPackage",
            "appActivity",
            "UiAutomator2",
        )
    ):
        return "ui_test_draft"
    if any(
        keyword in user_input
        for keyword in (
            "接口测试",
            "接口测试草稿",
            "接口自动化草稿",
            "pytest requests",
            "pytest + requests",
            "API",
            "api",
        )
    ):
        return "api_test_draft"
    if any(keyword in user_input for keyword in ("QA报告", "QA 报告", "qa report", "质量报告")):
        return "qa_report"
    if "resume" in lowered or "继续" in user_input:
        return "resume"
    return "resume"


def route_intent_fallback(user_input: str, *, reason: str = "") -> IntentRouteResult:
    """确定性路由：不因 LLM 不可用而中断自然语言入口。"""
    if _is_reset_request(user_input):
        return IntentRouteResult(intent="reset", summary="重置会话")

    prd_path, url = _extract_paths_fallback(user_input)
    intent = _infer_intent_fallback(user_input)
    summary = reason or "已使用确定性意图路由"
    if intent == "resume" and not any(keyword in user_input for keyword in ("继续", "resume")):
        summary = f"{summary}；未识别到新的受支持任务，保持当前会话"
    return IntentRouteResult(intent=intent, prd_path=prd_path, url=url, summary=summary)


def _is_reset_request(user_input: str) -> bool:
    lowered = user_input.lower().strip()
    return any(keyword in lowered or keyword in user_input for keyword in RESET_KEYWORDS)


def _parse_json_response(response_text: str) -> dict[str, object]:
    json_text = response_text.strip()
    if json_text.startswith("```"):
        lines = json_text.splitlines()
        start = 1 if lines and lines[0].startswith("```") else 0
        end = -1 if lines and lines[-1].strip() == "```" else len(lines)
        json_text = "\n".join(lines[start:end])
    data = json.loads(json_text)
    if not isinstance(data, dict):
        raise ValueError("语义路由响应必须是 JSON object")
    return data


def route_intent(user_input: str, config: OpenAICompatibleConfig) -> IntentRouteResult:
    """使用外部 Prompt 和 LLM 路由；失败时降级到当前确定性路由。"""
    if _is_reset_request(user_input):
        return IntentRouteResult(intent="reset", summary="重置会话")

    if not config.has_api_key:
        return route_intent_fallback(
            user_input,
            reason="缺少 LLM API Key，语义路由已降级",
        )

    try:
        adapter = OpenAICompatibleAdapter(config)
        response_text = adapter.generate_text(
            f"{_router_system_prompt()}\n\n用户输入：{user_input}"
        )
    except Exception as exc:  # noqa: BLE001
        return route_intent_fallback(
            user_input,
            reason=f"LLM 路由调用失败，已降级: {exc}",
        )

    try:
        data = _parse_json_response(response_text)
    except (json.JSONDecodeError, ValueError) as exc:
        return route_intent_fallback(
            user_input,
            reason=f"LLM 路由响应无效，已降级: {exc}",
        )

    result = IntentRouteResult(raw_response=response_text)
    intent = str(data.get("intent") or "")
    if intent not in SUPPORTED_INTENTS and intent not in CONTROL_INTENTS:
        result.errors.append(
            f"LLM 返回未知意图「{intent}」，支持: "
            + ", ".join((*SUPPORTED_INTENTS.keys(), *sorted(CONTROL_INTENTS)))
        )
        return result

    result.intent = intent
    result.prd_path = str(data["prd_path"]) if data.get("prd_path") else None
    result.url = str(data["url"]) if data.get("url") else None
    result.summary = str(data.get("summary") or "")
    return result
