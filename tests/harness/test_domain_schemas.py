from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from harness.domain.schemas.api_test_cases import (
    ApiTestCasesDraft,
    load_api_test_cases,
    load_api_test_cases_report_projection,
)
from harness.domain.schemas.execution_evidence import ExecutionEvidence, load_execution_evidence
from harness.infrastructure.workflow.engine import default_recorded_api_test_cases

UTC = timezone.utc


def test_api_cases_only_accept_current_v1_2() -> None:
    with pytest.raises(ValidationError, match="agentic-qa.api-cases.v1.2"):
        ApiTestCasesDraft.model_validate(
            {
                "schema_version": "agentic-qa.api-cases.v1",
                "artifact_type": "api_automation_cases",
                "status": "needs_human_review",
                "human_review_required": True,
                "business_rules": ["rule"],
                "source_refs": [],
                "cases": [],
                "review_questions": ["contract"],
            }
        )


def test_api_cases_v1_1_reader_normalizes_without_base_url_env() -> None:
    payload = default_recorded_api_test_cases("legacy reader").model_dump(mode="python")
    payload["schema_version"] = "agentic-qa.api-cases.v1.1"
    payload["base_url_env"] = "AGENTIC_QA_BASE_URL"

    normalized = load_api_test_cases(payload)

    assert normalized.schema_version == "agentic-qa.api-cases.v1.2"
    assert "base_url_env" not in normalized.model_dump(mode="python")


def test_v1_1_zero_assertion_case_is_report_only_metadata() -> None:
    payload = default_recorded_api_test_cases("legacy report").model_dump(mode="python")
    payload["schema_version"] = "agentic-qa.api-cases.v1.1"
    payload["base_url_env"] = "AGENTIC_QA_BASE_URL"
    payload["cases"][0].update(
        {
            "contract_status": "confirmed",
            "pending": [],
            "request": {"method": "GET", "path": "/health"},
            "assertions": [],
            "source_refs": [
                {
                    "source_type": "openapi",
                    "source_path": "sources/openapi.yml",
                    "chunk_id": "GET /health",
                    "locator": "GET /health",
                    "summary": "legacy operation",
                    "confidence": "high",
                }
            ],
        }
    )

    with pytest.raises(ValidationError, match="at least 1 item"):
        load_api_test_cases(payload)

    projection = load_api_test_cases_report_projection(payload)

    assert projection.schema_version == "agentic-qa.api-cases.v1.2"
    assert projection.cases[0].id == payload["cases"][0]["id"]
    assert projection.cases[0].assertions[0].type == "status_code"


def test_unconfirmed_api_case_cannot_look_executable() -> None:
    with pytest.raises(ValidationError, match="Input should be None"):
        ApiTestCasesDraft.model_validate(
            {
                "schema_version": "agentic-qa.api-cases.v1.2",
                "artifact_type": "api_automation_cases",
                "status": "needs_human_review",
                "human_review_required": True,
                "business_rules": ["RULE-001"],
                "source_refs": [
                    {
                        "source_type": "requirement",
                        "source_path": "sources/requirement.md",
                        "chunk_id": "rule-1",
                        "locator": "rule",
                        "summary": "业务规则",
                        "confidence": "medium",
                    }
                ],
                "cases": [
                    {
                        "id": "API-PENDING-001",
                        "title": "待确认接口",
                        "priority": "P1",
                        "contract_status": "partial",
                        "business_rule_refs": ["RULE-001"],
                        "review_status": "needs_human_review",
                        "review_questions": ["接口契约待确认"],
                        "source_refs": [
                            {
                                "source_type": "requirement",
                                "source_path": "sources/requirement.md",
                                "chunk_id": "rule-1",
                                "locator": "rule",
                                "summary": "业务规则",
                                "confidence": "medium",
                            }
                        ],
                        "pending": ["完整 OpenAPI"],
                        "request": {"method": "POST", "path": "/guessed"},
                        "assertions": [],
                        "variables": {},
                        "cleanup": [],
                    }
                ],
                "review_questions": ["接口契约待确认"],
            }
        )


def test_execution_summary_must_match_case_evidence() -> None:
    now = datetime.now(tz=UTC)
    with pytest.raises(ValidationError, match="does not match cases"):
        ExecutionEvidence.model_validate(
            {
                "schema_version": "agentic-qa.execution-evidence.v2",
                "run_id": "run-1",
                "source_cases_path": "cases.yml",
                "source_cases_schema_version": "agentic-qa.api-cases.v1.2",
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


def test_execution_evidence_v1_projects_to_v2_without_inventing_dispatch() -> None:
    now = datetime.now(tz=UTC)
    evidence = load_execution_evidence(
        {
            "schema_version": "agentic-qa.execution-evidence.v1",
            "run_id": "legacy-run",
            "source_cases_path": "cases.yml",
            "source_cases_schema_version": "agentic-qa.api-cases.v1.1",
            "started_at": now,
            "completed_at": now,
            "environment": {
                "name": "qa",
                "base_url_env": "BASE_URL",
                "base_url_configured": True,
                "allowed_methods": ["GET"],
                "request_timeout_seconds": 10,
            },
            "summary": {
                "total": 1,
                "executed": 1,
                "passed": 0,
                "failed": 0,
                "errors": 1,
                "blocked": 0,
            },
            "cases": [
                {
                    "case_id": "case-1::dataset-a",
                    "title": "legacy error",
                    "method": "GET",
                    "path": "/health",
                    "status": "error",
                    "started_at": now,
                    "completed_at": now,
                    "duration_ms": 1,
                }
            ],
        }
    )

    assert evidence.schema_version == "agentic-qa.execution-evidence.v2"
    assert evidence.cases[0].dataset_id == "dataset-a"
    assert evidence.cases[0].request_dispatched is False
    assert evidence.cases[0].correlation.diagnostics[0].code == ("legacy_request_dispatch_unknown")
