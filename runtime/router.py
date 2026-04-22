from __future__ import annotations

from pathlib import Path
import yaml

from runtime.intent_matcher import match_intent
from runtime.skill_registry import get_skill
from runtime.flow_engine import load_flow

ROOT = Path(__file__).resolve().parents[1]


def load_routing() -> dict:
    routing_file = ROOT / 'rules' / 'routing.yaml'
    return yaml.safe_load(routing_file.read_text(encoding='utf-8'))


def route_intent(intent_name: str) -> dict:
    routing = load_routing()
    return routing['intents'][intent_name]


def handle_user_input(user_text: str) -> dict:
    intent_name = match_intent(user_text)
    if not intent_name:
        return {
            'ok': False,
            'error': 'intent_not_matched',
            'user_text': user_text,
        }

    intent_config = route_intent(intent_name)
    flow = load_flow(intent_config['flow'])
    skill_name = intent_config['primary_skill']
    skill = get_skill(skill_name)

    return {
        'ok': True,
        'intent': intent_name,
        'flow': flow,
        'skill_name': skill_name,
        'skill_found': skill is not None,
        'user_text': user_text,
    }


if __name__ == '__main__':
    demo = '执行 pytest 冒烟并分析失败原因'
    print(handle_user_input(demo))
