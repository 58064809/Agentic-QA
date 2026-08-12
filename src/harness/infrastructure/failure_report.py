from __future__ import annotations

import hashlib
from pathlib import Path

from harness.application.quality import QualityContext
from harness.domain.models import RunSnapshot, StartRunCommand
from harness.domain.schemas.failure_triage import BugDraft, FailureTriageV2
from harness.domain.schemas.log_analysis import (
    PreparedFailureReport,
    PrepareFailureReportCommand,
    PrepareFailureReportResult,
)
from harness.infrastructure.persistence.common import create_only_json
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.quality.assessment import CandidateAssessmentService
from harness.infrastructure.quality.registry import QualityStrategyRegistry

NO_BUG_CATEGORIES = {"test-script", "test-data", "environment", "unknown"}


class FilesystemFailureReportService:
    def __init__(
        self,
        store: FilesystemStore,
        quality: QualityStrategyRegistry,
    ) -> None:
        self._store = store
        self._assessment = CandidateAssessmentService(quality)

    def prepare(self, command: PrepareFailureReportCommand) -> PrepareFailureReportResult:
        workspace_root = self._store.require_workspace(command.workspace_id).resolve()
        root = workspace_root / "executions" / command.execution_id / "triage" / "collections"
        if not root.is_dir():
            raise ValueError("failure triage collections do not exist")
        collections: list[tuple[Path, FailureTriageV2]] = []
        for item in sorted(root.iterdir()):
            triage_path = item / "failure-triage.json"
            if not triage_path.is_file():
                continue
            triage = FailureTriageV2.model_validate_json(triage_path.read_text(encoding="utf-8"))
            if triage.triage_status == "failed":
                continue
            if command.collection_id and triage.collection_id != command.collection_id:
                continue
            if command.case_id and triage.case_id != command.case_id:
                continue
            collections.append((item, triage))
        if not collections:
            raise ValueError("no matching validated failure triage")
        if command.collection_id is None:
            latest: dict[tuple[str, str | None], tuple[int, Path, FailureTriageV2]] = {}
            for item, triage in collections:
                key = (triage.case_id, triage.dataset_id)
                stamp = (item / "failure-triage.json").stat().st_mtime_ns
                if key not in latest or stamp > latest[key][0]:
                    latest[key] = (stamp, item, triage)
            collections = [(value[1], value[2]) for _, value in sorted(latest.items())]
        for item, triage in collections:
            self._validate_sources(item, triage, workspace_root, command.execution_id)
        reports = [
            self._prepare_one(command, collection_root, triage, workspace_root)
            for collection_root, triage in collections
        ]
        return PrepareFailureReportResult(
            workspace_id=command.workspace_id,
            execution_id=command.execution_id,
            reports=reports,
        )

    @staticmethod
    def _validate_sources(
        collection_root: Path,
        triage: FailureTriageV2,
        workspace_root: Path,
        execution_id: str,
    ) -> None:
        expected = {
            workspace_root / "executions" / execution_id / "evidence.json": (
                triage.execution_evidence_sha256
            ),
            collection_root / "log-evidence.json": triage.log_evidence_sha256,
            collection_root / "log-analysis.json": triage.log_analysis_sha256,
        }
        if triage.execution_id != execution_id or triage.collection_id != collection_root.name:
            raise ValueError("failure triage identity differs from requested collection")
        for path, digest in expected.items():
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise ValueError("failure triage source is unavailable") from exc
            if actual != digest:
                raise ValueError("failure triage source hash does not match")

    def _prepare_one(
        self,
        command: PrepareFailureReportCommand,
        collection_root: Path,
        triage: FailureTriageV2,
        workspace_root: Path,
    ) -> PreparedFailureReport:
        run_id = f"triage-{triage.collection_id.removeprefix('collection-')}"
        artifacts = ["failure_analysis"]
        bug = self._bug_draft(triage)
        if bug is not None:
            artifacts.append("bug_draft")
        try:
            snapshot = self._store.load_snapshot_read_only(command.workspace_id, run_id)
            if snapshot.request.expected_artifacts != artifacts:
                raise ValueError("existing triage run artifact scope differs")
            return PreparedFailureReport(
                collection_id=triage.collection_id,
                run_id=run_id,
                candidate_artifacts=artifacts,
            )
        except FileNotFoundError:
            pass
        snapshot = RunSnapshot(
            run_id=run_id,
            workspace_id=command.workspace_id,
            status="needs_human_review",
            request=StartRunCommand(
                workspace_id=command.workspace_id,
                goal=f"Review failure triage for {triage.case_id}",
                expected_artifacts=artifacts,
            ),
            interrupt={
                "type": "review_gate",
                "reason": "failure triage candidates require human review",
            },
        )
        self._store.create_run(snapshot)
        source_documents = {
            f"derived/{name}": path.read_text(encoding="utf-8")
            for name, path in {
                "execution-evidence.json": workspace_root
                / "executions"
                / command.execution_id
                / "evidence.json",
                "log-evidence.json": collection_root / "log-evidence.json",
                "log-analysis.json": collection_root / "log-analysis.json",
                "failure-triage.json": collection_root / "failure-triage.json",
            }.items()
        }
        source_bundle = self._store.create_derived_source_bundle(
            command.workspace_id, run_id, source_documents
        )
        contents = {"failure_analysis": self._analysis_markdown(triage)}
        attachment_bytes = {
            "failure-triage.json": (collection_root / "failure-triage.json").read_bytes(),
            "log-analysis.json": (collection_root / "log-analysis.json").read_bytes(),
            "log-evidence.json": (collection_root / "log-evidence.json").read_bytes(),
        }
        if bug is not None:
            create_only_json(collection_root / "bug-draft.json", bug.model_dump(mode="json"))
            contents["bug_draft"] = self._bug_markdown(bug)
            attachment_bytes["bug-draft.json"] = (collection_root / "bug-draft.json").read_bytes()
        candidates = []
        for artifact, content in contents.items():
            context = QualityContext(
                workspace_id=command.workspace_id,
                run_id=run_id,
                artifact=artifact,
                source_bundle=source_bundle,
            )
            assessment = self._assessment.assess(
                context=context,
                content=content,
                media_type="text/markdown",
                strategy_names=["generic-artifact-contracts"],
            )
            candidate, _ = self._store.commit_candidate(
                workspace=command.workspace_id,
                run_id=run_id,
                artifact=artifact,
                assessment=assessment,
                evidence=triage.available_evidence_refs,
                attachments={
                    name: (value, "application/json") for name, value in attachment_bytes.items()
                },
            )
            candidates.append(candidate)
        snapshot.candidates = candidates
        snapshot.review_status = {artifact: "needs_human_review" for artifact in artifacts}
        self._store.save_snapshot(snapshot)
        return PreparedFailureReport(
            collection_id=triage.collection_id,
            run_id=run_id,
            candidate_artifacts=artifacts,
        )

    @staticmethod
    def _bug_draft(triage: FailureTriageV2) -> BugDraft | None:
        primary = triage.primary
        if (
            triage.triage_status != "success"
            or primary is None
            or triage.likelihood == "insufficient_evidence"
            or primary.category in NO_BUG_CATEGORIES
            or not primary.evidence_refs
        ):
            return None
        return BugDraft(
            collection_id=triage.collection_id,
            execution_id=triage.execution_id,
            case_id=triage.case_id,
            dataset_id=triage.dataset_id,
            title=f"[{primary.category}] {primary.summary[:240]}",
            category=primary.category,
            likelihood=triage.likelihood,
            summary=primary.summary,
            evidence_refs=primary.evidence_refs,
            recommended_actions=triage.recommended_actions,
        )

    @staticmethod
    def _analysis_markdown(triage: FailureTriageV2) -> str:
        primary = triage.primary
        return "\n".join(
            [
                f"# Failure analysis: {triage.case_id}",
                "",
                f"- Collection: `{triage.collection_id}`",
                f"- Dataset: `{triage.dataset_id or 'default'}`",
                f"- Triage status: `{triage.triage_status}`",
                f"- Likelihood: `{triage.likelihood}`",
                f"- Category: `{primary.category if primary else 'unknown'}`",
                f"- Summary: {primary.summary if primary else 'No supported hypothesis'}",
                "- Evidence: " + ", ".join(primary.evidence_refs if primary else []),
                "",
                "## Recommended actions",
                *[f"- {item}" for item in triage.recommended_actions],
                "",
            ]
        )

    @staticmethod
    def _bug_markdown(bug: BugDraft) -> str:
        return "\n".join(
            [
                f"# {bug.title}",
                "",
                f"- Case: `{bug.case_id}`",
                f"- Dataset: `{bug.dataset_id or 'default'}`",
                f"- Category: `{bug.category}`",
                f"- Likelihood: `{bug.likelihood}`",
                "",
                "## Summary",
                bug.summary,
                "",
                "## Evidence",
                *[f"- `{item}`" for item in bug.evidence_refs],
                "",
                "## Recommended actions",
                *[f"- {item}" for item in bug.recommended_actions],
                "",
            ]
        )
