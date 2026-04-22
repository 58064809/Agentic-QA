from __future__ import annotations

from skills.runtime.analyze_requirement import analyze_requirement
from skills.runtime.generate_test_cases import generate_test_cases
from skills.runtime.run_pytest import run_pytest
from skills.runtime.analyze_pytest_result import analyze_pytest_result
from skills.runtime.search_logs import search_logs


SKILL_REGISTRY = {
    'analyze_requirement': analyze_requirement,
    'generate_test_cases': generate_test_cases,
    'run_pytest': run_pytest,
    'analyze_pytest_result': analyze_pytest_result,
    'search_logs': search_logs,
}


def get_skill(skill_name: str):
    return SKILL_REGISTRY.get(skill_name)
