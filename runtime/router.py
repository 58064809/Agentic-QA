from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from runtime.document_discovery import discover_requirement_context
from runtime.flow_engine import load_flow
from runtime.intent_matcher import match_intent_details
from runtime.resource_loader import load_markdown_resource
from runtime.resource_loader import summarize_resource
from runtime.output_writer import save_assistant_output
from runtime.response_formatter import format_skill_result
from runtime.skill_registry import get_skill

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKSPACE = ROOT / "workspace"
MARKER_ALIASES = {
    "smoke": "smoke",
    "冒烟": "smoke",
    "regression": "regression",
    "回归": "regression",
}
DEFAULT_LOG_KEYWORDS = ("error", "exception", "timeout", "traceback", "failed")


def load_routing() -> dict:
    routing_file = ROOT / "rules" / "routing.yaml"
    return yaml.safe_load(routing_file.read_text(encoding="utf-8"))


def route_intent(intent_name: str) -> dict[str, Any]:
    routing = load_routing()
    return routing["intents"][intent_name]


def _first_match(patterns: list[str], text: str, flags: int = 0) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1) if match.groups() else match.group(0)
    return ""


def build_test_execution_kwargs(user_text: str) -> dict[str, str]:
    target = _first_match(
        [
            r"([A-Za-z0-9_./\\-]+\.py(?:::[A-Za-z0-9_]+)*)",
            r"\b(tests(?:[/\\][A-Za-z0-9_.\\/-]+)?)\b",
        ],
        user_text,
        flags=re.IGNORECASE,
    ) or "tests"

    marker = _first_match([r"-m\s+([A-Za-z0-9_-]+)"], user_text, flags=re.IGNORECASE)
    if not marker:
        lowered = user_text.lower()
        for alias, normalized in MARKER_ALIASES.items():
            if alias in lowered or alias in user_text:
                marker = normalized
                break

    keyword = _first_match(
        [
            r"-k\s+[\"']?([A-Za-z0-9_./:\\-]+)[\"']?",
            r"关键字[:： ]+([A-Za-z0-9_./:\\-]+)",
            r"keyword[:： ]+([A-Za-z0-9_./:\\-]+)",
            r"用例名[:： ]+([A-Za-z0-9_./:\\-]+)",
            r"(test_[A-Za-z0-9_]+)",
        ],
        user_text,
        flags=re.IGNORECASE,
    )

    return {
        "target": target,
        "marker": marker,
        "keyword": keyword,
    }


def build_log_analysis_kwargs(user_text: str) -> dict[str, str]:
    file_path = _first_match(
        [
            r"[\"']([^\"']+\.log)[\"']",
            r"([A-Za-z]:\\[^\s\"']+\.log)",
            r"([A-Za-z0-9_./\\-]+\.log)",
        ],
        user_text,
        flags=re.IGNORECASE,
    )
    keyword = _first_match(
        [
            r"关键字[:： ]+([^\s\"']+)",
            r"keyword[:： ]+([^\s\"']+)",
            r"traceid[:= ]+([^\s\"']+)",
            r"trace_id[:= ]+([^\s\"']+)",
        ],
        user_text,
        flags=re.IGNORECASE,
    )
    if not keyword:
        lowered = user_text.lower()
        for candidate in DEFAULT_LOG_KEYWORDS:
            if candidate in lowered:
                keyword = candidate
                break
    return {
        "file_path": file_path,
        "keyword": keyword or "error",
    }


def build_skill_kwargs(intent_name: str, user_text: str, workspace_root: Path, routing_config: dict[str, Any]) -> dict[str, Any]:
    if intent_name == "result_analysis":
        return {"raw_text": user_text}
    if intent_name == "test_execution":
        kwargs = build_test_execution_kwargs(user_text)
        kwargs["workspace_root"] = str(workspace_root)
        return kwargs
    if intent_name == "log_analysis":
        kwargs = build_log_analysis_kwargs(user_text)
        kwargs["workspace_root"] = str(workspace_root)
        return kwargs

    kwargs: dict[str, Any] = {"user_text": user_text}
    if routing_config.get("requires_requirement_context"):
        kwargs["requirement_context"] = discover_requirement_context(workspace_root, user_text)
    return kwargs


def _resolve_output_root(default_root: Path, kwargs: dict[str, Any]) -> Path:
    requirement_context = kwargs.get("requirement_context")
    if isinstance(requirement_context, dict) and requirement_context.get("output_root"):
        return Path(requirement_context["output_root"])
    return default_root


def handle_user_input(user_text: str, workspace_root: str | Path | None = None) -> dict[str, Any]:
    match = match_intent_details(user_text)
    if match is None:
        return {
            "ok": False,
            "error": "intent_not_matched",
            "user_text": user_text,
        }

    current_workspace = Path(workspace_root) if workspace_root else DEFAULT_WORKSPACE if DEFAULT_WORKSPACE.exists() else ROOT
    intent_name = match.name
    routing = load_routing()
    assistant_config = routing["assistant"]
    intent_config = route_intent(intent_name)
    flow = load_flow(intent_config["flow"])
    skill = get_skill(intent_config["primary_skill"])

    agent_resource = load_markdown_resource(assistant_config["agent_file"])
    rule_resource = load_markdown_resource(intent_config["rule_file"])
    skill_doc_resource = load_markdown_resource(intent_config["skill_doc"])

    result: dict[str, Any] = {
        "ok": skill is not None,
        "assistant": assistant_config["name"],
        "intent": intent_name,
        "matched_keywords": list(match.matched_keywords),
        "flow": flow,
        "user_text": user_text,
        "loaded_resources": {
            "agent": summarize_resource(agent_resource),
            "rule": summarize_resource(rule_resource),
            "skill": summarize_resource(skill_doc_resource),
        },
    }

    if skill is None:
        result["error"] = "skill_not_found"
        return result

    kwargs = build_skill_kwargs(intent_name, user_text, current_workspace, intent_config)

    if intent_name == "test_execution":
        execution_result = skill(**kwargs)
        analyze_skill = get_skill("analyze_pytest_result")
        analysis_result = None
        if analyze_skill is not None:
            raw_text = f"{execution_result.get('stdout', '')}\n{execution_result.get('stderr', '')}".strip()
            analysis_result = analyze_skill(raw_text=raw_text)
        result["executed"] = True
        result["execution_kwargs"] = kwargs
        result["skill_result"] = execution_result
        result["analysis_result"] = analysis_result
        result["formatted_output"] = format_skill_result(intent_name, execution_result, analysis_result)
        result["saved_formatted_output"] = format_skill_result(intent_name, execution_result, analysis_result, full=True)
        result["saved_output"] = save_assistant_output(
            current_workspace,
            intent_name,
            result["saved_formatted_output"],
            execution_result,
        )
        return result

    skill_result = skill(**kwargs)
    output_root = _resolve_output_root(current_workspace, kwargs)
    result["executed"] = True
    result["skill_result"] = skill_result
    result["formatted_output"] = format_skill_result(intent_name, skill_result)
    result["saved_formatted_output"] = format_skill_result(intent_name, skill_result, full=True)
    result["saved_output"] = save_assistant_output(
        output_root,
        intent_name,
        result["saved_formatted_output"],
        skill_result,
    )
    if "requirement_context" in kwargs:
        result["requirement_context"] = kwargs["requirement_context"]
    return result
