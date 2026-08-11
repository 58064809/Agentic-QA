from __future__ import annotations

import pytest
from pydantic import ValidationError

from harness.domain.schemas.api_test_cases import ApiTestCasesDraft
from harness.infrastructure.workflow.engine import default_recorded_api_test_cases


def test_confirmed_api_case_requires_an_assertion() -> None:
    payload = default_recorded_api_test_cases("confirmed assertion contract").model_dump(
        mode="python"
    )
    case = payload["cases"][0]
    case["contract_status"] = "confirmed"
    case["request"]["method"] = "GET"
    case["request"]["path"] = "/health"
    case["source_refs"] = [
        {
            "source_type": "openapi",
            "source_path": "openapi.yml",
            "chunk_id": "GET /health",
            "locator": "GET /health",
            "summary": "health",
            "confidence": "high",
        }
    ]
    case["assertions"] = []

    with pytest.raises(ValidationError, match="at least 1 item"):
        ApiTestCasesDraft.model_validate(payload)


def test_unconfirmed_api_case_may_keep_assertions_empty() -> None:
    payload = default_recorded_api_test_cases("unconfirmed assertion contract").model_dump(
        mode="python"
    )
    case = payload["cases"][0]
    case["contract_status"] = "pending_confirmation"
    case["request"]["method"] = None
    case["request"]["path"] = None
    case["assertions"] = []

    draft = ApiTestCasesDraft.model_validate(payload)

    assert draft.cases[0].assertions == []
