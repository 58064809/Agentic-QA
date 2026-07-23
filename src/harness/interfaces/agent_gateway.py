from __future__ import annotations

from pathlib import Path

from harness.application.agent_request import (
    AgentRequest,
    AgentRequestCapabilities,
    AgentRequestResult,
)
from harness.application.use_cases import HarnessApplication
from harness.bootstrap import agent_source_roots, build_application
from harness.domain.models import ArtifactDiffResult, GetArtifactDiffQuery, RunRef, RunSnapshot


class AgentRequestGateway:
    """Restricted facade for external AI clients; it intentionally exposes no review writes."""

    def __init__(
        self,
        repo_root: Path | str = ".",
        *,
        allowed_source_roots: list[Path | str] | None = None,
        application: HarnessApplication | None = None,
    ) -> None:
        self._application = application
        if self._application is None:
            self._application = build_application(
                repo_root,
                allowed_source_roots=agent_source_roots(repo_root, allowed_source_roots),
            )

    def generate_from_sources(self, request: AgentRequest) -> AgentRequestResult:
        return self._application.submit_agent_request(request)

    def get_run(self, ref: RunRef) -> RunSnapshot:
        return self._application.get_run_read_only(ref)

    def get_artifact_diff(self, query: GetArtifactDiffQuery) -> ArtifactDiffResult:
        return self._application.get_artifact_diff(query)

    @staticmethod
    def get_capabilities() -> AgentRequestCapabilities:
        return AgentRequestCapabilities()
