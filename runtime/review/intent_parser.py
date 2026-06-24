from __future__ import annotations

import json
import re

from pydantic import ValidationError

from runtime.llm.config import OpenAICompatibleConfig
from runtime.llm.openai_compatible import OpenAICompatibleAdapter
from runtime.review.decision_schema import ReviewDecision, ReviewIntent

APPROVE_KEYWORDS = ("可以了", "确认", "通过", "发布吧", "发布正式产物", "approve", "approved")
REJECT_KEYWORDS = (
    "不通过",
    "不行",
    "驳回",
    "拒绝",
    "不要发布",
    "不发布",
    "reject",
    "rejected",
)
REVISE_KEYWORDS = ("补充", "修改", "调整", "修订", "完善", "增加", "revise")
HOLD_KEYWORDS = ("先放着", "待确认", "暂停", "先不要", "hold")
SHOW_DIFF_KEYWORDS = ("看看差异", "查看差异", "给我看看差异", "show diff", "diff")
NEGATION_KEYWORDS = ("不", "别", "暂停", "先不要", "不发布")
EXPLICIT_PROMOTE_KEYWORDS = ("确认", "通过", "发布", "approve")
LOW_CONFIDENCE_THRESHOLD = 0.8

TARGET_ALIASES: dict[str, tuple[str, ...]] = {
    "testcases": ("testcases", "testcase", "测试用例", "用例"),
    "requirement_analysis": (
        "requirement_analysis",
        "requirement-analysis",
        "需求分析",
        "分析",
    ),
    "api_test_draft": ("api_test_draft", "api-test-draft", "接口测试", "API测试", "api"),
    "ui_test_draft": ("ui_test_draft", "ui-test-draft", "UI测试", "ui"),
    "qa_report": ("qa_report", "qa-report", "QA报告", "qa report"),
}

REVIEW_DECISION_PROMPT = """你是 Review Gate 语义解析器。
你只能把用户自然语言转换为 JSON，不能裁决状态，不能发布产物，不能写文件。

只返回 JSON：
{
  "intent": "approve|reject|revise|hold|show_diff|clarify",
  "target_artifact": "testcases|requirement_analysis|api_test_draft|ui_test_draft|qa_report|null",
  "confidence": 0.0,
  "reason": "简短原因",
  "revision_request": null,
  "requires_confirmation": false
}
"""


def clarify_decision(reason: str, *, target_artifact: str | None = None) -> ReviewDecision:
    return ReviewDecision(
        intent=ReviewIntent.CLARIFY,
        target_artifact=target_artifact,
        confidence=1.0,
        reason=reason,
        requires_confirmation=True,
    )


def _json_from_text(text: str) -> dict:
    payload = text.strip()
    if payload.startswith("```"):
        lines = payload.splitlines()
        start = 1 if lines and lines[0].startswith("```") else 0
        end = -1 if lines and lines[-1].strip() == "```" else len(lines)
        payload = "\n".join(lines[start:end]).strip()
    return json.loads(payload)


def decision_from_llm_response(response_text: str) -> ReviewDecision:
    try:
        decision = ReviewDecision.model_validate(_json_from_text(response_text))
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        return clarify_decision(f"LLM 返回非法 ReviewDecision JSON: {exc}")
    return apply_safety_rules("", decision)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _target_from_text(text: str) -> str | None:
    lowered = text.lower()
    matched = [
        key
        for key, aliases in TARGET_ALIASES.items()
        if any(alias.lower() in lowered for alias in aliases)
    ]
    if not matched:
        return None
    if "只" in text and "testcases" in matched:
        return "testcases"
    return matched[0] if len(matched) == 1 else None


def _is_specific_positive_with_scoped_negation(text: str, target: str | None) -> bool:
    if target != "testcases":
        return False
    return bool(re.search(r"只\s*发布.*(测试用例|用例)", text)) and bool(
        re.search(r"不\s*发布.*(需求分析|分析)", text)
    )


def parse_review_decision_fallback(user_input: str) -> ReviewDecision:
    target = _target_from_text(user_input)

    if _contains_any(user_input, SHOW_DIFF_KEYWORDS):
        return ReviewDecision(
            intent=ReviewIntent.SHOW_DIFF,
            target_artifact=target,
            confidence=0.95,
            reason="用户请求查看候选产物差异",
        )
    if _contains_any(user_input, HOLD_KEYWORDS):
        return ReviewDecision(
            intent=ReviewIntent.HOLD,
            target_artifact=target,
            confidence=0.95,
            reason="用户表达暂停或待确认",
        )
    if _contains_any(user_input, REVISE_KEYWORDS):
        return ReviewDecision(
            intent=ReviewIntent.REVISE,
            target_artifact=target,
            confidence=0.9,
            reason="用户要求修订候选产物",
            revision_request=user_input,
        )
    if _is_specific_positive_with_scoped_negation(user_input, target):
        return ReviewDecision(
            intent=ReviewIntent.APPROVE,
            target_artifact=target,
            confidence=0.95,
            reason="用户明确只发布指定产物，并排除其他产物",
        )
    if _contains_any(user_input, REJECT_KEYWORDS):
        return ReviewDecision(
            intent=ReviewIntent.REJECT,
            target_artifact=target,
            confidence=0.95,
            reason="用户明确拒绝或不发布",
        )
    if _contains_any(user_input, APPROVE_KEYWORDS):
        return ReviewDecision(
            intent=ReviewIntent.APPROVE,
            target_artifact=target,
            confidence=0.95,
            reason="用户明确确认候选产物通过",
        )
    return clarify_decision("用户未明确表达审核动作", target_artifact=target)


def apply_safety_rules(user_input: str, decision: ReviewDecision) -> ReviewDecision:
    if decision.confidence < LOW_CONFIDENCE_THRESHOLD and not decision.requires_confirmation:
        decision = decision.model_copy(update={"requires_confirmation": True})

    if decision.intent == ReviewIntent.APPROVE:
        if user_input and _contains_any(user_input, NEGATION_KEYWORDS):
            if not _is_specific_positive_with_scoped_negation(user_input, decision.target_artifact):
                return clarify_decision("用户输入包含否定语义，拒绝直接 approve")
        if user_input and not _contains_any(user_input, EXPLICIT_PROMOTE_KEYWORDS):
            return clarify_decision("用户未明确表达确认、通过或发布")
    return decision


def parse_review_decision(
    user_input: str,
    *,
    config: OpenAICompatibleConfig | None = None,
) -> ReviewDecision:
    fallback = apply_safety_rules(user_input, parse_review_decision_fallback(user_input))
    if config is None or not config.has_api_key:
        return fallback

    try:
        adapter = OpenAICompatibleAdapter(config)
        response = adapter.generate_text(f"{REVIEW_DECISION_PROMPT}\n\n用户输入：{user_input}")
    except Exception:
        return fallback

    decision = decision_from_llm_response(response)
    return apply_safety_rules(user_input, decision)
