from __future__ import annotations

from actions.analyze_pytest_result import analyze_pytest_result
from actions.analyze_requirement import analyze_requirement
from actions.execute_test_workflow import execute_test_workflow
from actions.generate_test_cases import generate_test_cases
from actions.generate_test_script import generate_test_script
from actions.run_pytest import run_pytest
from actions.search_logs import search_logs

SKILL_REGISTRY = {
    "analyze_requirement": analyze_requirement,
    "generate_test_cases": generate_test_cases,
    "generate_test_script": generate_test_script,
    "execute_test_workflow": execute_test_workflow,
    "run_pytest": run_pytest,
    "analyze_pytest_result": analyze_pytest_result,
    "search_logs": search_logs,
}


def get_skill(skill_name: str):
    return SKILL_REGISTRY.get(skill_name)
