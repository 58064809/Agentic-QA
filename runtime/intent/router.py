from __future__ import annotations

from pathlib import Path

from runtime.config import load_app_config
from runtime.llm.config import OpenAICompatibleConfig
from runtime.llm.intent_router import IntentRouteResult, route_intent, route_intent_fallback


def route_user_intent(user_input: str, repo_root: Path) -> IntentRouteResult:
    app_config = load_app_config(repo_root)
    if not app_config.llm.enabled or not app_config.llm.semantic_router_enabled:
        return route_intent_fallback(
            user_input,
            reason="配置已禁用 LLM 语义路由，已使用确定性路由",
        )
    config = OpenAICompatibleConfig.from_app_config(app_config.llm)
    return route_intent(user_input, config)
