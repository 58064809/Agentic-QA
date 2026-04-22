from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from runtime.intent_matcher import match_intent
from runtime.skill_registry import get_skill
from runtime.flow_engine import load_flow

ROOT = Path(__file__).resolve().parents[1]
LOW_RISK_INTENTS = {
    'requirement_analysis',
    'test_case_generation',
    'result_analysis',
}


def load_routing() -> dict:
    routing_file = ROOT / 'rules' / 'routing.yaml'
    return yaml.safe_load(routing_file.read_text(encoding='utf-8'))


def route_intent(intent_name: str) -> dict:
    routing = load_routing()
    return routing['intents'][intent_name]


def build_skill_kwargs(intent_name: str, user_text: str) -> dict[str, Any]:
    if intent_name in {'requirement_analysis', 'test_case_generation'}:
        return {'text': user_text}
    if intent_name == 'result_analysis':
        return {'raw_text': user_text}
    return {}


def build_test_execution_kwargs(user_text: str) -> dict[str, Any]:
    text = user_text.lower()
    target = 'tests'
    marker = ''
    keyword = ''

    if 'smoke' in text or '冒烟' in user_text:
        marker = 'smoke'
    if 'router' in text:
        keyword = 'router'
    if 'intent' in text:
        keyword = 'intent'

    return {
        'target': target,
        'marker': marker,
        'keyword': keyword,
    }


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

    result: dict[str, Any] = {
        'ok': True,
        'intent': intent_name,
        'flow': flow,
        'skill_name': skill_name,
        'skill_found': skill is not None,
        'user_text': user_text,
    }

    if skill is None:
        result['ok'] = False
        result['error'] = 'skill_not_found'
        return result

    if intent_name in LOW_RISK_INTENTS:
        kwargs = build_skill_kwargs(intent_name, user_text)
        result['executed'] = True
        result['skill_result'] = skill(**kwargs)
        return result

    if intent_name == 'test_execution':
        test_kwargs = build_test_execution_kwargs(user_text)
        execution_result = skill(**test_kwargs)
        analyze_skill = get_skill('analyze_pytest_result')
        analysis_result = None
        if analyze_skill is not None:
            raw_text = f"{execution_result.get('stdout', '')}\n{execution_result.get('stderr', '')}".strip()
            analysis_result = analyze_skill(raw_text=raw_text)

        result['executed'] = True
        result['execution_mode'] = 'run_and_analyze'
        result['execution_kwargs'] = test_kwargs
        result['skill_result'] = execution_result
        result['analysis_result'] = analysis_result
        return result

    result['executed'] = False
    result['execution_mode'] = 'planned_only'
    return result


if __name__ == '__main__':
    demos = [
        '请分析这个需求并输出测试点和风险点',
        '请帮我写测试用例，输出 markdown 表格',
        '分析这段 pytest 失败结果，AssertionError: status code mismatch',
        '执行 pytest router 相关用例并分析失败原因',
    ]
    for demo in demos:
        print('---')
        print(handle_user_input(demo))
