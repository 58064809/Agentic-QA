from __future__ import annotations

from typing import Literal

from pydantic import Field

from harness.domain.models import StrictModel
from harness.domain.schemas.execution_evidence import ExecutionEvidence


class RunApiScenarioResult(StrictModel):
    schema_version: Literal["agentic-qa.harness.run-api-scenario-result.v1"] = (
        "agentic-qa.harness.run-api-scenario-result.v1"
    )
    workspace_id: str
    execution_id: str
    environment: str
    status: Literal["passed", "failed"]
    source_cases_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_path: str
    evidence_path: str
    summary_path: str
    evidence: ExecutionEvidence
