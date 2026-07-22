from __future__ import annotations

import pytest
from pydantic import ValidationError

from harness.domain.schemas.failure_triage import FailureTriage


def test_error_or_blocked_cannot_be_linked_to_bug() -> None:
    payload = {
        "schema_version": "agentic-qa.failure-triage.v1",
        "source_evidence_path": "evidence.json",
        "source_evidence_schema": "agentic-qa.execution-evidence.v1",
        "source_run_id": "run-1",
        "summary": {
            "total_non_passed": 1,
            "assertion_failures": 0,
            "execution_errors": 1,
            "policy_blocked": 0,
            "bug_candidates": 1,
        },
        "observations": [
            {
                "case_id": "case-1",
                "title": "network error",
                "method": "GET",
                "path": "/health",
                "evidence_status": "error",
                "category": "execution_error",
                "root_cause_status": "unconfirmed",
                "evidence_ref": "cases/0",
                "observation": "timeout",
                "bug_candidate_id": "bug-1",
            }
        ],
        "bug_candidates": [
            {
                "id": "bug-1",
                "case_id": "case-1",
                "title": "not allowed",
                "status": "needs_human_review",
                "evidence_ref": "cases/0",
                "request": "GET /health",
                "expected": ["response"],
                "actual": ["timeout"],
                "pending": ["root cause"],
            }
        ],
    }
    with pytest.raises(ValidationError, match="cannot create bug candidates"):
        FailureTriage.model_validate(payload)
