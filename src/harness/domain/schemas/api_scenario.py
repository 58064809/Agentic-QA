from __future__ import annotations

from typing import Literal

from pydantic import Field

from harness.domain.models import StrictModel
from harness.domain.schemas.execution_evidence import ExecutionEvidence


class RunApiScenarioResult(StrictModel):
    schema_version: Literal["agentic-qa.harness.run-api-scenario-result.v2"] = (
        "agentic-qa.harness.run-api-scenario-result.v2"
    )
    workspace_id: str
    execution_id: str
    environment: str
    status: Literal["passed", "failed"]
    source_cases_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_path: str
    evidence_path: str
    summary_path: str
    event_log_path: str
    report_summary_path: str
    cleanup_summary_path: str
    allure_results_path: str
    allure_report_path: str | None = None
    report_status: Literal["generated", "results_only"]
    evidence: ExecutionEvidence
