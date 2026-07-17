from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from harness.schemas.api_test_cases import ApiTestCasesDraft
from harness.schemas.execution_evidence import ExecutionEvidence

UTC = timezone.utc


def test_api_cases_only_accept_v1_1() -> None:
    with pytest.raises(ValidationError, match="agentic-qa.api-cases.v1.1"):
        ApiTestCasesDraft.model_validate(
            {
                "schema_version": "agentic-qa.api-cases.v1",
                "artifact_type": "api_automation_cases",
                "status": "needs_human_review",
                "human_review_required": True,
                "base_url_env": "AGENTIC_QA_BASE_URL",
                "business_rules": ["rule"],
                "source_refs": [],
                "cases": [],
                "review_questions": ["contract"],
            }
        )


def test_execution_summary_must_match_case_evidence() -> None:
    now = datetime.now(tz=UTC)
    with pytest.raises(ValidationError, match="does not match cases"):
        ExecutionEvidence.model_validate(
            {
                "schema_version": "agentic-qa.execution-evidence.v1",
                "run_id": "run-1",
                "source_cases_path": "cases.yml",
                "source_cases_schema_version": "agentic-qa.api-cases.v1.1",
                "started_at": now,
                "completed_at": now,
                "environment": {
                    "name": "staging",
                    "base_url_env": "AGENTIC_QA_BASE_URL",
                    "base_url_configured": True,
                    "allowed_methods": ["GET"],
                    "request_timeout_seconds": 10,
                },
                "summary": {
                    "total": 1,
                    "executed": 0,
                    "passed": 0,
                    "failed": 0,
                    "errors": 0,
                    "blocked": 1,
                },
                "cases": [
                    {
                        "case_id": "case-1",
                        "title": "health",
                        "method": "GET",
                        "path": "/health",
                        "status": "passed",
                        "started_at": now,
                        "completed_at": now,
                        "duration_ms": 0,
                        "assertions": [],
                    }
                ],
            }
        )
