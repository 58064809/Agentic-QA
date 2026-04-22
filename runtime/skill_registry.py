from __future__ import annotations

from skills.runtime.analyze_requirement import analyze_requirement
from skills.runtime.run_pytest import run_pytest
from skills.runtime.search_logs import search_logs


SKILL_REGISTRY = {
    'analyze_requirement': analyze_requirement,
    'run_pytest': run_pytest,
    'search_logs': search_logs,
}


def get_skill(skill_name: str):
    return SKILL_REGISTRY.get(skill_name)
