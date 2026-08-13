from __future__ import annotations

import hashlib
from pathlib import Path

from harness.application.source import (
    SourceBundle,
    SourceCompleteness,
    SourceDocument,
    SourceIngestionLimits,
)
from harness.domain.models import ApprovedArtifactVersion
from harness.domain.schemas.execution_evidence import (
    EXECUTION_EVIDENCE_SCHEMA_VERSION,
    ExecutionEvidence,
)
from harness.domain.schemas.knowledge import (
    KnowledgeDeleteCommand,
    KnowledgeDeleteResult,
    KnowledgeFreshness,
    KnowledgeIndexResult,
    KnowledgeIndexRunCommand,
    KnowledgeMigrateResult,
    KnowledgeReindexCommand,
    KnowledgeReindexResult,
    KnowledgeStatus,
    KnowledgeTrust,
)
from harness.domain.schemas.local_config import AgenticQaLocalConfig
from harness.infrastructure.knowledge_store import (
    PostgresKnowledgeStore,
    embedding_provider_from_config,
)
from harness.infrastructure.persistence.common import atomic_json
from harness.infrastructure.persistence.filesystem import FilesystemStore


class KnowledgeService:
    """Administrator-only knowledge lifecycle; it is never exposed as an Agent tool."""

    def __init__(
        self,
        files: FilesystemStore,
        database: PostgresKnowledgeStore,
        config: AgenticQaLocalConfig,
    ) -> None:
        self.files = files
        self.database = database
        self.config = config
        self.embedding_provider = embedding_provider_from_config(config.rag.embedding)

    def migrate(self) -> KnowledgeMigrateResult:
        return KnowledgeMigrateResult(applied_version=self.database.migrate())

    def status(self, workspace_id: str) -> KnowledgeStatus:
        self.files.require_workspace(workspace_id)
        return self.database.status(workspace_id)

    def index_run(self, command: KnowledgeIndexRunCommand) -> KnowledgeIndexResult:
        snapshot = self.files.load_snapshot_read_only(command.workspace_id, command.run_id)
        if snapshot.status != "published":
            raise PermissionError("only reviewed, published runs may enter long-term knowledge")
        journal = self._validated_publication(command.workspace_id, command.run_id, snapshot)
        publication_id = str(journal["publication_id"])
        self.database.enqueue_publication(publication_id, command.workspace_id, command.run_id)
        try:
            counts = self._index_published(snapshot, journal)
        except Exception as exc:
            self.database.mark_publication(
                publication_id,
                status="failed",
                error=type(exc).__name__,
            )
            self._mark_journal(command.workspace_id, command.run_id, "failed")
            raise
        self.database.mark_publication(publication_id, status="completed")
        self._mark_journal(command.workspace_id, command.run_id, "completed")
        return KnowledgeIndexResult(
            workspace_id=command.workspace_id,
            run_id=command.run_id,
            documents=counts["documents"],
            chunks=counts["chunks"],
            embedded=counts["embedded"],
            status="already_indexed" if counts["chunks"] == 0 else "completed",
        )

    def publication_committed(self, workspace_id: str, run_id: str) -> None:
        try:
            self.index_run(KnowledgeIndexRunCommand(workspace_id=workspace_id, run_id=run_id))
        except Exception:
            # Publication truth is intentionally independent from the derived knowledge index.
            return

    def reindex(self, command: KnowledgeReindexCommand) -> KnowledgeReindexResult:
        workspace = self.files.require_workspace(command.workspace_id)
        indexed: list[str] = []
        runs = workspace / "runs"
        for state_path in sorted(runs.glob("*/state.json")) if runs.is_dir() else []:
            run_id = state_path.parent.name
            snapshot = self.files.load_snapshot_read_only(command.workspace_id, run_id)
            if snapshot.status != "published":
                continue
            self.index_run(
                KnowledgeIndexRunCommand(workspace_id=command.workspace_id, run_id=run_id)
            )
            indexed.append(run_id)
        executions = self._index_verified_executions(command.workspace_id, workspace)
        return KnowledgeReindexResult(
            workspace_id=command.workspace_id,
            indexed_runs=indexed,
            indexed_executions=executions,
        )

    def delete(self, command: KnowledgeDeleteCommand) -> KnowledgeDeleteResult:
        self.files.require_workspace(command.workspace_id)
        self.database.delete_document(command.workspace_id, command.document_id)
        return KnowledgeDeleteResult(
            workspace_id=command.workspace_id,
            document_id=command.document_id,
        )

    def _validated_publication(self, workspace_id: str, run_id: str, snapshot):
        journal_path = (
            self.files.require_workspace(workspace_id)
            / "reviews"
            / run_id
            / "publication-intent.json"
        )
        if not journal_path.is_file():
            raise ValueError("published run is missing its publication journal")
        import json

        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if (
            journal.get("status") != "committed"
            or journal.get("workspace_id") != workspace_id
            or journal.get("run_id") != run_id
        ):
            raise ValueError("publication journal is incomplete or belongs to another run")
        versions = [ApprovedArtifactVersion.model_validate(item) for item in journal["versions"]]
        self.files.artifacts.verify_many(snapshot, versions)
        return journal

    def _index_published(self, snapshot, journal: dict) -> dict[str, int]:
        totals = {"documents": 0, "chunks": 0, "embedded": 0}
        source = self.files.load_source_bundle(snapshot.workspace_id, snapshot.run_id)
        self._add(
            totals,
            self.database.index_source_bundle(
                snapshot.workspace_id,
                snapshot.run_id,
                source,
                max_chunk_characters=self.config.rag.retrieval.max_chunk_characters,
                embedding_provider=self.embedding_provider,
                trust=KnowledgeTrust.REFERENCE_ONLY,
                trust_resolver=_source_trust,
                freshness=KnowledgeFreshness.HISTORICAL,
            ),
        )
        versions = [ApprovedArtifactVersion.model_validate(item) for item in journal["versions"]]
        for version in versions:
            candidate = self.files.load_candidate(
                workspace=snapshot.workspace_id,
                run_id=snapshot.run_id,
                artifact=version.artifact,
            )
            if candidate is None:
                raise ValueError("approved candidate is missing during knowledge indexing")
            paths = [(Path(version.path), version.content_sha256)] + [
                (Path(item.path), item.content_sha256) for item in candidate.attachments
            ]
            bundle = _asset_bundle(self.files.repo_root, version.artifact, paths)
            trust = _artifact_trust(version.artifact)
            self._add(
                totals,
                self.database.index_source_bundle(
                    snapshot.workspace_id,
                    snapshot.run_id,
                    bundle,
                    max_chunk_characters=self.config.rag.retrieval.max_chunk_characters,
                    embedding_provider=self.embedding_provider,
                    trust=trust,
                    freshness=KnowledgeFreshness.HISTORICAL,
                ),
            )
        return totals

    def _mark_journal(self, workspace_id: str, run_id: str, status: str) -> None:
        path = (
            self.files.require_workspace(workspace_id)
            / "reviews"
            / run_id
            / "publication-intent.json"
        )
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["knowledge_index_status"] = status
        atomic_json(path, payload)

    def _index_verified_executions(self, workspace_id: str, workspace: Path) -> list[str]:
        import json

        indexed: list[str] = []
        executions = workspace / "executions"
        for manifest_path in sorted(executions.glob("*/manifest.json")):
            execution_id = manifest_path.parent.name
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                manifest.get("workspace_id") != workspace_id
                or manifest.get("execution_id") != execution_id
                or manifest.get("execution_status") != "completed"
            ):
                continue
            relative = manifest.get("evidence_path")
            expected_hash = manifest.get("evidence_sha256")
            if not isinstance(relative, str) or not isinstance(expected_hash, str):
                continue
            evidence_path = (workspace / relative).resolve()
            if workspace.resolve() not in evidence_path.parents or not evidence_path.is_file():
                raise ValueError("execution evidence path escaped its workspace or is missing")
            raw = evidence_path.read_bytes()
            actual_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError("execution evidence hash changed")
            payload = json.loads(raw)
            if payload.get("schema_version") != EXECUTION_EVIDENCE_SCHEMA_VERSION:
                continue
            ExecutionEvidence.model_validate(payload)
            text = raw.decode("utf-8")
            bundle = SourceBundle(
                parser_version="execution-evidence-v2",
                limits=SourceIngestionLimits(),
                documents=(
                    SourceDocument(
                        path=f"executions/{execution_id}/evidence.json",
                        raw_sha256=actual_hash,
                        parsed_sha256="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                        byte_size=len(raw),
                        text=text,
                        completeness=SourceCompleteness.COMPLETE,
                    ),
                ),
                completeness=SourceCompleteness.COMPLETE,
                bundle_hash=actual_hash,
            )
            self.database.index_source_bundle(
                workspace_id,
                execution_id,
                bundle,
                max_chunk_characters=self.config.rag.retrieval.max_chunk_characters,
                embedding_provider=self.embedding_provider,
                trust=KnowledgeTrust.EXECUTION_EVIDENCE,
                freshness=KnowledgeFreshness.HISTORICAL,
            )
            indexed.append(execution_id)
        return indexed

    @staticmethod
    def _add(total: dict[str, int], value: dict[str, int]) -> None:
        for key in total:
            total[key] += value[key]


def _asset_bundle(
    repo_root: Path,
    artifact: str,
    paths: list[tuple[Path, str]],
) -> SourceBundle:
    documents: list[SourceDocument] = []
    for index, (relative, expected_hash) in enumerate(paths):
        absolute = (repo_root / relative).resolve()
        if not absolute.is_file():
            raise ValueError("reviewed knowledge asset is missing")
        raw = absolute.read_bytes()
        actual = "sha256:" + hashlib.sha256(raw).hexdigest()
        if actual != expected_hash:
            raise ValueError("reviewed knowledge asset hash changed")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        documents.append(
            SourceDocument(
                path=f"published/{artifact}/{index:04d}-{relative.name}",
                raw_sha256=actual,
                parsed_sha256="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                byte_size=len(raw),
                text=text,
                completeness=SourceCompleteness.COMPLETE,
            )
        )
    identity = "\n".join(f"{item.path}:{item.raw_sha256}" for item in documents).encode()
    return SourceBundle(
        parser_version="reviewed-assets-v1",
        limits=SourceIngestionLimits(),
        documents=tuple(documents),
        completeness=SourceCompleteness.COMPLETE,
        bundle_hash="sha256:" + hashlib.sha256(identity).hexdigest(),
    )


def _source_trust(document: SourceDocument) -> KnowledgeTrust:
    path = document.path.casefold()
    if "openapi" in path or "swagger" in path:
        return KnowledgeTrust.REVIEWED_CONTRACT
    if "testcase" in path or "test-case" in path or "/tests/" in path:
        return KnowledgeTrust.REVIEWED_TEST_ASSET
    if "bug" in path or "failure-triage" in path:
        return KnowledgeTrust.REVIEWED_BUG
    return KnowledgeTrust.REFERENCE_ONLY


def _artifact_trust(artifact: str) -> KnowledgeTrust:
    if artifact == "requirement_analysis":
        return KnowledgeTrust.REVIEWED_REQUIREMENT
    if artifact in {"testcases", "api_test_draft"}:
        return KnowledgeTrust.REVIEWED_TEST_ASSET
    if artifact in {"bug_draft", "failure_triage"}:
        return KnowledgeTrust.REVIEWED_BUG
    return KnowledgeTrust.REVIEWED_ASSET
