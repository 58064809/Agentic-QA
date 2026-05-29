"""LLM 语义路由：从自然语言提取意图和文档来源"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from runtime.llm.config import OpenAICompatibleConfig
from runtime.llm.openai_compatible import OpenAICompatibleAdapter

# ── 支持的所有意图 ────────────────────────────────────────────

SUPPORTED_INTENTS: dict[str, str] = {
    "requirement_analysis": "需求分析",
    "testcase_generation": "测试用例生成",
    "api_test_generation": "API 接口测试生成",
    "ui_test_generation": "UI 端到端测试生成",
    "test_execution": "测试执行",
    "failure_analysis": "失败分析",
    "bug_draft": "缺陷草稿生成",
    "report_generation": "QA 报告生成",
    "archive": "归档",
    "resume": "继续上次对话",
}

INTENT_DESCRIPTIONS = "\n".join(
    f"   - {k}: {v}" for k, v in SUPPORTED_INTENTS.items()
)

INTENT_ROUTER_SYSTEM_PROMPT = f"""你是一个 QA 工作流路由助手。从用户输入中提取以下信息，只返回 JSON 格式：

{{
  "intent": "意图名称",
  "prd_path": null 或本地绝对路径,
  "url": null 或飞书链接,
  "summary": "简短任务摘要"
}}

意图选项：
{INTENT_DESCRIPTIONS}

规则：
- 如果用户提到本地文件路径（.md/.pdf/.docx 等），提取完整绝对路径到 prd_path。
- 如果用户提到飞书链接（feishu.cn 或 lark 开头的 URL），提取到 url。
- 如果没有明确意图，设为 "resume" 表示继续上次对话。
- 如果用户说"重新开始""重置""从头开始"，intent 设为 "reset"。
- 只输出 JSON，不要额外文字。
"""


# ── 本地文件路径检测（LLM 不可用时的后备） ─────────────────────

LOCAL_PATH_RE = re.compile(
    r"""
    [a-zA-Z]:\\(?:[^\\"']+\\)*[^\\"']+\.(?:md|pdf|docx|txt|html|xlsx)
    |
    /(?:[^/"']+/)*[^/"']+\.(?:md|pdf|docx|txt|html|xlsx)
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


def _extract_paths_fallback(user_input: str) -> tuple[str | None, str | None]:
    """关键词匹配提取路径和 URL（LLM 不可用时的后备）。"""
    prd_path = None
    url = None

    m = LOCAL_PATH_RE.search(user_input)
    if m:
        prd_path = m.group(0).strip()

    m = URL_RE.search(user_input)
    if m:
        url = m.group(0).strip().rstrip(".)>")

    return prd_path, url


def _is_reset_request(user_input: str) -> bool:
    lowered = user_input.lower().strip()
    for kw in RESET_KEYWORDS:
        if kw in lowered or kw in user_input:
            return True
    return False


def route_intent(user_input: str, config: OpenAICompatibleConfig) -> IntentRouteResult:
    """用 LLM 从用户输入中提取意图和文档来源。

    如果 LLM 不可用（无 API key），返回错误。
    """
    result = IntentRouteResult()

    # 先检查重置意图
    if _is_reset_request(user_input):
        result.intent = "reset"
        result.summary = "重置会话"
        return result

    # 检查 LLM 是否可用
    if not config.has_api_key:
        result.errors.append(
            "缺少 API Key（DEEPSEEK_API_KEY），无法进行语义路由。\n"
            "请先设置环境变量，参考 .env.example。"
        )
        # 后备：用关键词匹配提取路径信息（至少能返回有用的错误信息）
        prd_path, url = _extract_paths_fallback(user_input)
        result.prd_path = prd_path
        result.url = url
        return result

    # 调用 LLM 路由
    try:
        adapter = OpenAICompatibleAdapter(config)
        prompt = f"用户输入: {user_input}"
        response_text = adapter.generate_text(
            f"{INTENT_ROUTER_SYSTEM_PROMPT}\n\n{prompt}"
        )
    except Exception as e:
        result.errors.append(f"LLM 路由调用失败: {e}")
        return result

    # 解析 JSON
    result.raw_response = response_text
    try:
        # 从响应中提取 JSON（处理可能的 markdown 包裹）
        json_str = response_text.strip()
        if json_str.startswith("```"):
            # 去掉 ```json ... ``` 包裹
            lines = json_str.split("\n")
            start = 1 if lines[0].startswith("```") else 0
            end = -1 if lines[-1].strip() == "```" else len(lines)
            json_str = "\n".join(lines[start:end])
        data = json.loads(json_str)
    except json.JSONDecodeError:
        result.errors.append(f"LLM 返回非 JSON 格式: {response_text[:200]}")
        return result

    intent = data.get("intent", "")
    if intent not in SUPPORTED_INTENTS and intent != "reset":
        result.errors.append(
            f"LLM 返回未知意图「{intent}」，支持: {', '.join(SUPPORTED_INTENTS.keys())}"
        )
        return result

    result.intent = intent
    result.prd_path = data.get("prd_path") or None
    result.url = data.get("url") or None
    result.summary = data.get("summary", "")
    return result
