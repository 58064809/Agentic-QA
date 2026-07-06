from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from runtime.tools.api_case_runner import ApiCase, execute_api_case, load_api_cases


class FakeResponse:
    status_code = 200

    def json(self):
        return {"code": 0, "data": {"ok": True}}


def test_load_api_cases_from_yaml(tmp_path):
    path = tmp_path / "api-test-cases.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "agentic-qa.api-cases.v1",
                "cases": [
                    {
                        "id": "API-001",
                        "title": "登录成功",
                        "method": "POST",
                        "path": "/api/login",
                        "request": {"json": {"phone": "13800138000"}},
                        "expected": {"status_code": [200], "json_contains_keys": ["code"]},
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    cases = load_api_cases(Path(path))

    assert len(cases) == 1
    assert cases[0].id == "API-001"
    assert cases[0].method == "POST"


def test_execute_api_case_resolves_env_placeholders_and_asserts_response():
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse()

    case = ApiCase(
        id="API-001",
        title="登录成功",
        method="POST",
        path="/api/login",
        request={
            "headers": {"Authorization": "Bearer ${AGENTIC_QA_TEST_TOKEN}"},
            "json": {"phone": "13800138000"},
        },
        expected={"status_code": [200], "json_contains_keys": ["code", "data"]},
    )

    result = execute_api_case(
        case,
        base_url="https://test.example.com",
        env={"AGENTIC_QA_TEST_TOKEN": "test-token"},
        request_func=fake_request,
    )

    assert result.passed
    assert calls == [
        (
            "POST",
            "https://test.example.com/api/login",
            {
                "headers": {"Authorization": "Bearer test-token"},
                "params": None,
                "json": {"phone": "13800138000"},
                "timeout": 10,
            },
        )
    ]


def test_execute_api_case_rejects_absolute_url():
    case = ApiCase(
        id="API-001",
        title="禁止完整域名",
        method="GET",
        path="https://prod.example.com/api/login",
        request={},
        expected={"status_code": [200]},
    )

    with pytest.raises(ValueError, match="完整环境域名"):
        execute_api_case(case, base_url="https://test.example.com")
