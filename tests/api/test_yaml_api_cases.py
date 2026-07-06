from __future__ import annotations

import os
from pathlib import Path

import pytest

from runtime.tools.api_case_runner import execute_api_case, load_api_cases


def _configured_cases():
    path = os.getenv("AGENTIC_QA_API_CASES_FILE")
    if not path:
        pytest.skip(
            "AGENTIC_QA_API_CASES_FILE 未配置，跳过 YAML 接口用例执行",
            allow_module_level=True,
        )
    return load_api_cases(Path(path))


@pytest.mark.parametrize("case", _configured_cases(), ids=lambda case: case.id)
def test_yaml_api_case(case):
    base_url = os.getenv("AGENTIC_QA_BASE_URL")
    if not base_url:
        pytest.skip("AGENTIC_QA_BASE_URL 未配置，跳过真实接口请求")
    execute_api_case(case, base_url=base_url)
