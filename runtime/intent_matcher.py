from __future__ import annotations

import re
from dataclasses import dataclass

from runtime.intent_rules_loader import load_intent_rules


@dataclass(frozen=True)
class IntentCandidate:
    name: str
    score: int
    matched_keywords: tuple[str, ...]
    negated_keywords: tuple[str, ...]


@dataclass(frozen=True)
class IntentMatch:
    name: str
    score: int
    matched_keywords: tuple[str, ...]
    confidence: float
    alternatives: tuple[str, ...] = ()
    candidates: tuple[IntentCandidate, ...] = ()
    needs_clarification: bool = False
    reason: str = ""


_RULES_DOC = load_intent_rules()


def _tuple_list(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    return (str(value),)


def _load_rules_from_doc() -> tuple[dict[str, dict[str, tuple[str, ...]]], tuple[str, ...], int, int]:
    intents = _RULES_DOC.get("intents", {}) if isinstance(_RULES_DOC, dict) else {}
    rules: dict[str, dict[str, tuple[str, ...]]] = {}
    if isinstance(intents, dict):
        for intent_name, sections in intents.items():
            if not isinstance(sections, dict):
                continue
            rules[intent_name] = {key: _tuple_list(value) for key, value in sections.items()}

    priority = _tuple_list(_RULES_DOC.get("priority") if isinstance(_RULES_DOC, dict) else None)
    min_confident = int(_RULES_DOC.get("min_confident_score", 45)) if isinstance(_RULES_DOC, dict) else 45
    min_margin = int(_RULES_DOC.get("min_margin", 12)) if isinstance(_RULES_DOC, dict) else 12
    return rules, priority, min_confident, min_margin


INTENT_RULES, INTENT_PRIORITY, MIN_CONFIDENT_SCORE, MIN_MARGIN = _load_rules_from_doc()
if not INTENT_RULES:
    raise RuntimeError("Intent rules are missing; expected rules/intents/index.yaml")
if not INTENT_PRIORITY:
    INTENT_PRIORITY = tuple(INTENT_RULES.keys())


def _normalize_text(user_text: str) -> str:
    return user_text.lower().strip()


def _compact_text(user_text: str) -> str:
    return re.sub(r"[\s\u3000]+", "", _normalize_text(user_text))


def _contains_pattern(text: str, compact_text: str, pattern: str) -> bool:
    normalized = pattern.lower().strip()
    if not normalized:
        return False
    compact_pattern = re.sub(r"[\s\u3000]+", "", normalized)
    return normalized in text or compact_pattern in compact_text


def _find_hits(text: str, compact_text: str, patterns: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(pattern for pattern in patterns if _contains_pattern(text, compact_text, pattern))


def _score_candidate(intent_name: str, text: str, compact_text: str) -> IntentCandidate:
    rules = INTENT_RULES[intent_name]
    strong_hits = _find_hits(text, compact_text, rules.get("strong", ()))
    verb_hits = _find_hits(text, compact_text, rules.get("verbs", ()))
    object_hits = _find_hits(text, compact_text, rules.get("objects", ()))
    context_hits = _find_hits(text, compact_text, rules.get("context", ()))
    negative_hits = _find_hits(text, compact_text, rules.get("negative", ()))
    deny_hits = _find_hits(text, compact_text, rules.get("deny", ()))

    score = 0
    score += len(strong_hits) * 42
    score += len(verb_hits) * 12
    score += len(object_hits) * 15
    score += len(context_hits) * 8
    if verb_hits and object_hits:
        score += 16
    if strong_hits and context_hits:
        score += 8
    if intent_name == "test_workflow_execution" and _is_workflow_combo(text, compact_text):
        score += 60
    if intent_name == "result_analysis" and _looks_like_failure_analysis(text, compact_text):
        score += 20
    if intent_name == "test_execution" and _looks_like_pytest_command(text):
        score += 18
    if intent_name == "log_analysis" and _looks_like_log_query(text):
        score += 15
    if intent_name == "requirement_analysis" and _looks_like_requirement_analysis(text):
        score += 15

    score -= len(negative_hits) * 14
    score -= len(deny_hits) * 55

    matched = strong_hits + verb_hits + object_hits + context_hits
    return IntentCandidate(
        name=intent_name,
        score=max(score, 0),
        matched_keywords=_dedupe(matched),
        negated_keywords=_dedupe(negative_hits + deny_hits),
    )


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _is_workflow_combo(text: str, compact_text: str) -> bool:
    generation = _find_hits(text, compact_text, ("生成", "产出", "输出", "generate"))
    cases = _find_hits(text, compact_text, ("测试用例", "用例", "test case", "cases"))
    execution = _find_hits(text, compact_text, ("执行", "运行", "跑", "pytest", "run"))
    return bool(generation and cases and execution)


def _looks_like_failure_analysis(text: str, compact_text: str) -> bool:
    return bool(
        _find_hits(text, compact_text, ("pytest", "traceback", "assertionerror", "failed", "失败", "报错"))
        and _find_hits(text, compact_text, ("分析", "定位", "排查", "原因"))
    )


def _looks_like_pytest_command(text: str) -> bool:
    return bool(re.search(r"pytest(\s+[-\w./:\\]+)?", text) or "::" in text or "tests/" in text or "tests\\" in text)


def _looks_like_log_query(text: str) -> bool:
    return ".log" in text or "traceid" in text or "trace_id" in text


def _looks_like_requirement_analysis(text: str) -> bool:
    return bool(re.search(r"(分析|review|梳理).{0,8}(需求|prd|requirement)", text))


def _rank_candidates(user_text: str) -> list[IntentCandidate]:
    text = _normalize_text(user_text)
    compact_text = _compact_text(user_text)
    candidates = [_score_candidate(intent_name, text, compact_text) for intent_name in INTENT_PRIORITY]
    candidates = [candidate for candidate in candidates if candidate.score > 0 and candidate.matched_keywords]
    candidates.sort(key=lambda item: (-item.score, INTENT_PRIORITY.index(item.name)))
    return candidates


def _confidence_for(top: IntentCandidate, second: IntentCandidate | None) -> float:
    margin = top.score - (second.score if second else 0)
    raw = 0.35 + min(top.score, 120) / 150 + min(max(margin, 0), 60) / 200
    return round(min(raw, 0.99), 2)


def _needs_clarification(top: IntentCandidate, second: IntentCandidate | None) -> tuple[bool, str]:
    if top.score < MIN_CONFIDENT_SCORE:
        return True, "top_intent_score_too_low"
    if second and second.score >= MIN_CONFIDENT_SCORE and top.score - second.score < MIN_MARGIN:
        return True, "top_candidates_too_close"
    if len(top.matched_keywords) == 1 and top.score < 60:
        return True, "matched_signals_too_sparse"
    return False, ""


def match_intent_details(user_text: str) -> IntentMatch | None:
    candidates = _rank_candidates(user_text)
    if not candidates:
        return None

    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    confidence = _confidence_for(top, second)
    needs_clarification, reason = _needs_clarification(top, second)
    alternatives = tuple(candidate.name for candidate in candidates[1:3])

    return IntentMatch(
        name=top.name,
        score=top.score,
        matched_keywords=top.matched_keywords,
        confidence=confidence,
        alternatives=alternatives,
        candidates=tuple(candidates[:3]),
        needs_clarification=needs_clarification,
        reason=reason,
    )


def match_intent(user_text: str) -> str | None:
    match = match_intent_details(user_text)
    if match is None or match.needs_clarification:
        return None
    return match.name
