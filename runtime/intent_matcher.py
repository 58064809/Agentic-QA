from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntentMatch:
    name: str
    score: int
    matched_keywords: tuple[str, ...]


INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "requirement_analysis": (
        "分析需求",
        "需求分析",
        "看需求",
        "拆需求",
        "review prd",
        "review requirement",
        "分析prd",
        "看prd",
    ),
    "test_case_generation": (
        "测试用例",
        "用例",
        "测试点",
        "case",
        "test case",
        "testcase",
    ),
    "script_generation": (
        "生成脚本",
        "脚本",
        "测试脚本",
        "自动化脚本",
        "pytest 脚本",
        "pytest脚本",
        "pytest script",
        "生成pytest",
    ),
    "test_execution": (
        "执行pytest",
        "跑pytest",
        "执行用例",
        "跑用例",
        "冒烟",
        "smoke",
        "回归",
        "regression",
        "pytest",
    ),
    "result_analysis": (
        "分析pytest结果",
        "分析失败结果",
        "失败原因",
        "报错分析",
        "traceback",
        "assertionerror",
        "结果分析",
    ),
    "log_analysis": (
        "查日志",
        "分析日志",
        "日志分析",
        "搜日志",
        "traceid",
        "error log",
        "日志",
    ),
}
INTENT_PRIORITY = (
    "result_analysis",
    "test_execution",
    "script_generation",
    "test_case_generation",
    "log_analysis",
    "requirement_analysis",
)


def _normalize_text(user_text: str) -> str:
    return user_text.lower().strip()


def match_intent_details(user_text: str) -> IntentMatch | None:
    text = _normalize_text(user_text)

    if "脚本" in text and "pytest" in text:
        return IntentMatch(
            name="script_generation",
            score=100,
            matched_keywords=("pytest", "脚本"),
        )

    if "分析" in text and ("需求" in text or "prd" in text):
        return IntentMatch(
            name="requirement_analysis",
            score=100,
            matched_keywords=("分析", "需求"),
        )

    matches: list[IntentMatch] = []

    for intent_name, keywords in INTENT_KEYWORDS.items():
        matched_keywords = tuple(keyword for keyword in keywords if keyword.lower() in text)
        if not matched_keywords:
            continue
        score = sum(len(keyword) for keyword in matched_keywords)
        matches.append(IntentMatch(name=intent_name, score=score, matched_keywords=matched_keywords))

    if not matches:
        return None

    matches.sort(key=lambda item: (-item.score, INTENT_PRIORITY.index(item.name)))
    return matches[0]


def match_intent(user_text: str) -> str | None:
    match = match_intent_details(user_text)
    return match.name if match else None
