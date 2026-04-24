from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from runtime.action_protocol import normalize_action_result
from runtime.skill_registry import get_skill


@dataclass(frozen=True)
class PostSkillResult:
    name: str
    ok: bool
    error: str
    data: dict[str, Any]


def run_post_skills(
    post_skill_names: list[str] | tuple[str, ...],
    *,
    intent_name: str,
    user_text: str,
    action_result: dict[str, Any],
    action_ok: bool,
) -> dict[str, PostSkillResult]:
    results: dict[str, PostSkillResult] = {}
    for post_skill_name in post_skill_names:
        runner = _post_skill_runner(post_skill_name)
        results[post_skill_name] = runner(
            intent_name=intent_name,
            user_text=user_text,
            action_result=action_result,
            action_ok=action_ok,
        )
    return results


def _post_skill_runner(post_skill_name: str) -> Callable[..., PostSkillResult]:
    if post_skill_name == "analyze_pytest_result":
        return _run_analyze_pytest_result

    def runner(*, intent_name: str, user_text: str, action_result: dict[str, Any], action_ok: bool) -> PostSkillResult:
        return _run_generic_post_skill(
            intent_name=intent_name,
            user_text=user_text,
            action_result=action_result,
            action_ok=action_ok,
            post_skill_name=post_skill_name,
        )

    return runner


def _run_analyze_pytest_result(
    *,
    intent_name: str,
    user_text: str,
    action_result: dict[str, Any],
    action_ok: bool,
) -> PostSkillResult:
    skill = get_skill("analyze_pytest_result")
    if skill is None:
        return PostSkillResult(name="analyze_pytest_result", ok=False, error="skill_not_found", data={})

    raw_text = f"{action_result.get('stdout', '')}\n{action_result.get('stderr', '')}".strip()
    normalized = normalize_action_result(skill(raw_text=raw_text, execution_result=action_result))
    return PostSkillResult(
        name="analyze_pytest_result",
        ok=normalized.ok,
        error=normalized.error,
        data=normalized.data,
    )


def _run_generic_post_skill(
    *,
    intent_name: str,
    user_text: str,
    action_result: dict[str, Any],
    action_ok: bool,
    post_skill_name: str | None = None,
) -> PostSkillResult:
    name = post_skill_name or ""
    skill = get_skill(name)
    if skill is None:
        return PostSkillResult(name=name, ok=False, error="skill_not_found", data={})

    normalized = normalize_action_result(skill(user_text=user_text, action_result=action_result))
    return PostSkillResult(name=name, ok=normalized.ok, error=normalized.error, data=normalized.data)

