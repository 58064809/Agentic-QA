from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from harness.contracts import ARTIFACT_TYPES, ReviewDecision, TaskRequest
from harness.harness import Harness


def run_offline_eval() -> dict[str, Any]:
    """Deterministic no-network scenario covering all first-release artifact routes."""
    with TemporaryDirectory(prefix="agentic-qa-eval-") as temporary:
        harness = Harness(Path(temporary))
        harness.init_workspace("offline-eval")
        snapshot = harness.run(
            TaskRequest(
                workspace="offline-eval",
                goal="离线评测：覆盖需求、设计、API、UI、执行、分诊和报告闭环",
                expected_artifacts=list(ARTIFACT_TYPES),
            )
        )
        candidate_types = {candidate.artifact for candidate in snapshot.candidates}
        generated = candidate_types == set(ARTIFACT_TYPES)
        gate_held = snapshot.status == "needs_human_review"
        published = harness.resume(
            snapshot.run_id,
            ReviewDecision(
                intent="approve",
                target_artifact="all",
                reason="offline deterministic eval",
            ),
        )
        checks = {
            "all_artifact_routes": generated,
            "review_gate_interrupt": gate_held,
            "deterministic_promote": published.status == "published",
        }
        return {
            "schema_version": "agentic-qa.harness.eval-result.v1",
            "passed": all(checks.values()),
            "checks": checks,
            "artifact_count": len(candidate_types),
        }
