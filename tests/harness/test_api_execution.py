from __future__ import annotations

import pytest

from harness import ExecutionProfile
from harness.api_execution import execute_api_cases
from harness.schemas.api_test_cases import ApiTestCase
from harness.schemas.execution_evidence import ExecutionEvidence


class FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


def _case(case_id: str, method: str, expected: int = 200) -> ApiTestCase:
    return ApiTestCase.model_validate(
        {
            "id": case_id,
            "title": f"case {case_id}",
            "priority": "P1",
            "contract_status": "confirmed",
            "business_rule_refs": ["rule-1"],
            "review_status": "needs_human_review",
            "review_questions": ["environment"],
            "source_refs": [
                {
                    "source_type": "openapi",
                    "source_path": "sources/openapi.json",
                    "chunk_id": "openapi.demo.GET.1",
                    "locator": f"{method} /api/{case_id.lower()}",
                    "summary": "recorded contract",
                    "confidence": "high",
                }
            ],
            "pending": [],
            "request": {"method": method, "path": f"/api/{case_id.lower()}"},
            "assertions": [
                {"type": "status_code", "expected": [expected]},
                {"type": "json_field_exists", "path": "$.code"},
            ],
            "variables": {},
            "cleanup": [],
        }
    )


def test_execution_records_pass_failure_and_policy_block() -> None:
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        status = 200 if url.endswith("api-001") else 500
        return FakeResponse(status, {"code": 0})

    evidence = execute_api_cases(
        [_case("API-001", "GET"), _case("API-002", "GET"), _case("API-003", "POST")],
        run_id="run-test",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="staging",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://secret.example.test"},
        request_func=request,
    )

    assert evidence.summary.model_dump() == {
        "total": 3,
        "executed": 2,
        "passed": 1,
        "failed": 1,
        "errors": 0,
        "blocked": 1,
    }
    assert [item.status for item in evidence.cases] == ["passed", "failed", "blocked"]
    assert len(calls) == 2
    assert "secret.example.test" not in evidence.model_dump_json()


def test_execution_error_redacts_url_and_environment_secret() -> None:
    def request(method, url, **kwargs):
        raise RuntimeError(f"request failed for {url} token-secret")

    evidence = execute_api_cases(
        [_case("API-001", "GET")],
        run_id="run-test",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="staging",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://secret.example.test", "TOKEN": "token-secret"},
        request_func=request,
    )

    assert evidence.cases[0].status == "error"
    assert evidence.cases[0].error == "request failed for <redacted-url> <redacted>"


def test_execution_evidence_rejects_inconsistent_summary() -> None:
    evidence = execute_api_cases(
        [_case("API-001", "GET")],
        run_id="run-test",
        source_cases_path="published/api_test_draft/current.yml",
        profile=ExecutionProfile(
            environment="staging",
            base_url_env="TEST_BASE_URL",
            allowed_http_methods=["GET"],
        ),
        env={"TEST_BASE_URL": "https://example.test"},
        request_func=lambda *_args, **_kwargs: FakeResponse(200, {"code": 0}),
    ).model_dump(mode="json")
    evidence["summary"]["passed"] = 0

    with pytest.raises(ValueError, match="does not match cases"):
        ExecutionEvidence.model_validate(evidence)
