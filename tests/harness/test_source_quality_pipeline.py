from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from harness.application.quality import (
    ArtifactVariant,
    NormalizationOperation,
    NormalizationOperationKind,
    NormalizationProposal,
    QualityComponentConfiguration,
    QualityContext,
    StrategyRequirements,
    StrategyResult,
)
from harness.application.source import (
    SourceBundle,
    SourceCompleteness,
    SourceDocument,
    SourceIngestionLimits,
)
from harness.domain.models import (
    ApprovedArtifactVersion,
    ArtifactCandidate,
    RunSnapshot,
    StartRunCommand,
)
from harness.infrastructure.persistence import artifact_repository
from harness.infrastructure.persistence.filesystem import FilesystemStore
from harness.infrastructure.persistence.source_bundle_repository import _critical_structure_issues
from harness.infrastructure.quality.assessment import CandidateAssessmentService
from harness.infrastructure.quality.generic import GenericArtifactStrategy
from harness.infrastructure.quality.normalization import (
    SafeMarkdownNormalizer,
    apply_safe_normalization,
)
from harness.infrastructure.quality.registry import QualityStrategyRegistry


class RequiresSourcesStrategy:
    name = "requires-sources"
    version = "1.0.0"
    requirements = StrategyRequirements(requires_sources=True, requires_complete_sources=True)
    configuration = QualityComponentConfiguration()

    def evaluate(self, context: QualityContext, content: str) -> StrategyResult:
        del context, content
        return StrategyResult()


class UnsafeNormalizer:
    name = "unsafe-test-normalizer"
    version = "1.0.0"
    configuration = QualityComponentConfiguration()

    def propose(self, context: QualityContext, content: str) -> NormalizationProposal:
        del context, content
        raise ValueError("semantic projection changed")


def _empty_bundle(value: str = "0") -> SourceBundle:
    return SourceBundle(
        parser_version="test",
        limits=SourceIngestionLimits(),
        completeness=SourceCompleteness.EMPTY,
        bundle_hash="sha256:" + value * 64,
    )


def _registry(*, requires_sources: bool = False) -> QualityStrategyRegistry:
    registry = QualityStrategyRegistry()
    registry.register(GenericArtifactStrategy())
    if requires_sources:
        registry.register(RequiresSourcesStrategy())
    return registry


def _workspace_store(tmp_path: Path, limits: SourceIngestionLimits | None = None):
    store = FilesystemStore(tmp_path, source_limits=limits)
    workspace = store.init_workspace("demo", quality_policies=[])
    snapshot = RunSnapshot(
        run_id="run-1",
        workspace_id="demo",
        status="planning",
        request=StartRunCommand(workspace_id="demo", goal="test"),
    )
    store.create_run(snapshot)
    return store, workspace


def test_source_bundle_preserves_warnings_hashes_and_run_snapshot(tmp_path: Path) -> None:
    limits = SourceIngestionLimits(max_parsed_characters=10)
    store, workspace = _workspace_store(tmp_path, limits)
    (workspace / "sources/good.md").write_text(
        "# 说明\n\n这是完整正文，并且会被解析。", encoding="utf-8"
    )
    (workspace / "sources/non-utf8.bin").write_bytes(b"\xff\xfe")

    bundle = store.create_source_bundle("demo", "run-1")
    original_text = next(item.text for item in bundle.documents if item.path == "sources/good.md")
    non_utf8 = next(item for item in bundle.documents if item.path.endswith("non-utf8.bin"))

    assert bundle.bundle_hash.startswith("sha256:")
    assert non_utf8.raw_sha256 is not None
    assert non_utf8.parsed_sha256 is None
    assert {issue.code for issue in non_utf8.issues} == {"source_non_utf8"}
    assert any(item.truncated for item in bundle.documents)

    (workspace / "sources/good.md").write_text("changed after run start", encoding="utf-8")
    restored = store.load_source_bundle("demo", "run-1")
    restored_text = next(item.text for item in restored.documents if item.path == "sources/good.md")
    assert restored_text == original_text
    assert restored.bundle_hash == bundle.bundle_hash


def test_load_source_bundle_rejects_missing_snapshot(tmp_path: Path) -> None:
    store, workspace = _workspace_store(tmp_path)
    (workspace / "sources/prd.md").write_text("# PRD\n\n正文", encoding="utf-8")
    store.create_source_bundle("demo", "run-1")
    (workspace / "runs/run-1/source-snapshot/0000.txt").unlink()

    with pytest.raises(ValueError, match=r"source snapshot 缺失: sources/prd\.md"):
        store.load_source_bundle("demo", "run-1")


def test_load_source_bundle_rejects_tampered_snapshot(tmp_path: Path) -> None:
    store, workspace = _workspace_store(tmp_path)
    (workspace / "sources/prd.md").write_text("# PRD\n\n正文", encoding="utf-8")
    store.create_source_bundle("demo", "run-1")
    (workspace / "runs/run-1/source-snapshot/0000.txt").write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match=r"source snapshot hash 校验失败: sources/prd\.md"):
        store.load_source_bundle("demo", "run-1")


def test_load_source_bundle_rejects_unexpected_snapshot(tmp_path: Path) -> None:
    store, workspace = _workspace_store(tmp_path)
    store.create_source_bundle("demo", "run-1")
    snapshot = workspace / "runs/run-1/source-snapshot"
    snapshot.mkdir(exist_ok=True)
    (snapshot / "0003.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(ValueError, match="source snapshot 存在未声明文件: 0003.txt"):
        store.load_source_bundle("demo", "run-1")


def test_unavailable_document_cannot_have_parsed_hash() -> None:
    with pytest.raises(ValueError, match="unavailable.*parsed_sha256"):
        SourceDocument(
            path="sources/prd.md",
            parsed_sha256="sha256:" + "0" * 64,
            completeness=SourceCompleteness.UNAVAILABLE,
        )


def test_critical_empty_section_is_blocker_but_valid_table_is_not(tmp_path: Path) -> None:
    store, workspace = _workspace_store(tmp_path)
    (workspace / "sources/empty.md").write_text(
        "# 奖励配置\n\n# 其他说明\n\n正文。\n", encoding="utf-8"
    )
    (workspace / "sources/table.md").write_text(
        "规则表：\n\n| 档位 | 奖励 |\n|---|---|\n| 1 | 10 |\n", encoding="utf-8"
    )

    bundle = store.create_source_bundle("demo", "run-1")
    issues = [issue for document in bundle.documents for issue in document.issues]

    assert any(issue.code == "suspected_missing_structure" for issue in issues)
    assert not any(
        issue.code == "suspected_missing_structure" and issue.path == "sources/table.md"
        for issue in issues
    )


def test_truncated_critical_section_is_inconclusive_not_blocker(tmp_path: Path) -> None:
    prefix = "# 奖励配置\n"
    limits = SourceIngestionLimits(max_parsed_characters=len(prefix))
    store, workspace = _workspace_store(tmp_path, limits)
    (workspace / "sources/rules.md").write_text(prefix + "正文位于截断范围之后", encoding="utf-8")

    bundle = store.create_source_bundle("demo", "run-1")
    issues = [issue for document in bundle.documents for issue in document.issues]

    assert {issue.code for issue in issues} == {
        "source_truncated",
        "structure_check_inconclusive",
    }


def _structure_codes(text: str) -> set[str]:
    return {issue.code for issue in _critical_structure_issues("sources/prd.md", text, False)}


def test_heading_inside_fenced_code_is_ignored() -> None:
    assert not _structure_codes("```markdown\n# 配置\n```")


def test_heading_inside_blockquote_is_ignored() -> None:
    assert not _structure_codes("> # 配置")


def test_hashtag_text_is_not_heading() -> None:
    assert not _structure_codes("#配置")


def test_numbered_list_is_not_misclassified_as_heading() -> None:
    assert not _structure_codes("1. 配置")


def test_table_without_data_row_is_missing_structure() -> None:
    assert "suspected_missing_structure" in _structure_codes("# 配置\n\n| 档位 | 奖励 |\n|---|---|")


def test_html_comment_does_not_count_as_section_content() -> None:
    assert "suspected_missing_structure" in _structure_codes("# 配置\n<!-- 假正文 -->")


def test_valid_setext_heading_is_detected() -> None:
    assert "suspected_missing_structure" in _structure_codes("奖励配置\n====")


def test_valid_numbered_colon_heading_is_detected() -> None:
    assert "suspected_missing_structure" in _structure_codes("1. 奖励配置：")


def test_hard_limit_does_not_publish_a_partial_file_hash(tmp_path: Path) -> None:
    limits = SourceIngestionLimits(max_parse_bytes=1024, max_hash_bytes=1024)
    store, workspace = _workspace_store(tmp_path, limits)
    (workspace / "sources/oversized.md").write_bytes(b"x" * 1025)

    bundle = store.create_source_bundle("demo", "run-1")
    document = bundle.documents[0]

    assert document.raw_sha256 is None
    assert document.text is None
    assert document.completeness == SourceCompleteness.UNAVAILABLE
    assert {issue.code for issue in document.issues} == {"source_unhashed_due_to_limit"}


def test_oversized_unparsed_source_still_has_streamed_raw_hash(tmp_path: Path) -> None:
    limits = SourceIngestionLimits(max_parse_bytes=1024, max_hash_bytes=4096)
    store, workspace = _workspace_store(tmp_path, limits)
    (workspace / "sources/oversized.md").write_bytes(b"x" * 2048)

    document = store.create_source_bundle("demo", "run-1").documents[0]

    assert document.raw_sha256 == "sha256:" + hashlib.sha256(b"x" * 2048).hexdigest()
    assert document.parsed_sha256 is None and document.text is None
    assert {issue.code for issue in document.issues} == {"source_unparsed_due_to_limit"}


def test_source_content_change_changes_bundle_hash_even_when_not_parsed(tmp_path: Path) -> None:
    limits = SourceIngestionLimits(max_parse_bytes=1024, max_hash_bytes=4096)
    first_store, first_workspace = _workspace_store(tmp_path / "first", limits)
    second_store, second_workspace = _workspace_store(tmp_path / "second", limits)
    (first_workspace / "sources/large.md").write_bytes(b"a" * 2048)
    (second_workspace / "sources/large.md").write_bytes(b"b" * 2048)

    assert first_store.create_source_bundle("demo", "run-1").bundle_hash != (
        second_store.create_source_bundle("demo", "run-1").bundle_hash
    )


def test_unhashed_source_blocks_complete_source_strategy(tmp_path: Path) -> None:
    limits = SourceIngestionLimits(max_parse_bytes=1024, max_hash_bytes=1024)
    store, workspace = _workspace_store(tmp_path, limits)
    (workspace / "sources/large.md").write_bytes(b"a" * 2048)
    bundle = store.create_source_bundle("demo", "run-1")
    assessment = CandidateAssessmentService(_registry(requires_sources=True)).assess(
        context=QualityContext(
            workspace_id="demo", run_id="run-1", artifact="qa_report", source_bundle=bundle
        ),
        content="report",
        media_type="text/markdown",
        strategy_names=["generic-artifact-contracts", "requires-sources"],
    )
    assert not assessment.report.verdict_for(ArtifactVariant.RAW)
    assert any(
        issue.code == "required_source_unavailable"
        for issue in assessment.report.variants[0].issues
    )


def test_stream_hash_does_not_load_entire_file_into_memory(tmp_path: Path, monkeypatch) -> None:
    from harness.infrastructure.persistence import source_bundle_repository as source_repository

    monkeypatch.setattr(source_repository, "HASH_CHUNK_BYTES", 128)
    limits = SourceIngestionLimits(max_parse_bytes=1024, max_hash_bytes=4096)
    store, workspace = _workspace_store(tmp_path, limits)
    (workspace / "sources/large.md").write_bytes(b"a" * 2048)

    document = store.create_source_bundle("demo", "run-1").documents[0]
    assert document.raw_sha256 is not None
    assert source_repository.HASH_CHUNK_BYTES < (document.byte_size or 0)


def test_empty_sources_only_block_strategies_that_require_them() -> None:
    context = QualityContext(
        workspace_id="demo",
        run_id="run-1",
        artifact="qa_report",
        source_bundle=_empty_bundle(),
    )
    generic = CandidateAssessmentService(_registry()).assess(
        context=context,
        content="report",
        media_type="text/markdown",
        strategy_names=["generic-artifact-contracts"],
    )
    required = CandidateAssessmentService(_registry(requires_sources=True)).assess(
        context=context,
        content="report",
        media_type="text/markdown",
        strategy_names=["generic-artifact-contracts", "requires-sources"],
    )

    assert generic.report.verdict_for(ArtifactVariant.RAW)
    assert not required.report.verdict_for(ArtifactVariant.RAW)
    assert any(
        issue.code == "required_source_unavailable" for issue in required.report.variants[0].issues
    )


def test_legacy_candidate_quality_flag_is_query_only_and_not_persisted() -> None:
    candidate = ArtifactCandidate.model_validate(
        {
            "artifact": "qa_report",
            "path": "legacy.md",
            "quality_passed": True,
        }
    )

    assert "quality_passed" not in candidate.model_dump()
    with pytest.raises(ValueError, match="provenance"):
        candidate.version_ref(ArtifactVariant.RAW)


def test_assessment_key_is_canonical_sensitive_and_excludes_environment(monkeypatch) -> None:
    service = CandidateAssessmentService(_registry())
    context = QualityContext(
        workspace_id="demo",
        run_id="run-1",
        artifact="qa_report",
        source_bundle=_empty_bundle(),
    )
    arguments = {
        "context": context,
        "content": "report",
        "media_type": "text/markdown",
        "strategy_names": ["generic-artifact-contracts"],
    }
    first = service.assessment_key(**arguments)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-affect-assessment")
    assert service.assessment_key(**arguments) == first
    assert service.assessment_key(**{**arguments, "content": "changed"}) != first
    assert (
        service.assessment_key(
            **{
                **arguments,
                "context": context.model_copy(update={"source_bundle": _empty_bundle("1")}),
            }
        )
        != first
    )


def test_normalization_is_representation_only() -> None:
    proposal = NormalizationProposal(
        operations=(
            NormalizationOperation(kind=NormalizationOperationKind.NORMALIZE_LINE_ENDINGS),
            NormalizationOperation(kind=NormalizationOperationKind.TRIM_TRAILING_WHITESPACE),
            NormalizationOperation(kind=NormalizationOperationKind.ENSURE_FINAL_NEWLINE),
            NormalizationOperation(
                kind=NormalizationOperationKind.NORMALIZE_MARKDOWN_TABLE_DELIMITER_SPACING
            ),
        )
    )
    raw = "| 字段 | 值 |  \r\n|---|---|\r\n| 档位 | 1 |"

    normalized = apply_safe_normalization(raw, proposal)

    assert "档位" in normalized and "1" in normalized
    assert normalized.endswith("\n")
    assert "\r" not in normalized


def _unsafe_normalization_assessment():
    registry = _registry()
    registry.register_normalizer(UnsafeNormalizer())
    return CandidateAssessmentService(registry).assess(
        context=QualityContext(
            workspace_id="demo",
            run_id="run-1",
            artifact="qa_report",
            source_bundle=_empty_bundle(),
        ),
        content="valid raw report",
        media_type="text/markdown",
        strategy_names=["generic-artifact-contracts"],
    )


def test_unsafe_normalizer_does_not_block_valid_raw() -> None:
    assessment = _unsafe_normalization_assessment()
    assert assessment.report.verdict_for(ArtifactVariant.RAW)
    assert not assessment.report.variants[0].issues


def test_unsafe_normalizer_does_not_create_normalized_variant() -> None:
    assessment = _unsafe_normalization_assessment()
    assert assessment.normalized_content is None
    assert {item.variant for item in assessment.report.variants} == {ArtifactVariant.RAW}


def test_normalizer_failure_is_recorded_in_quality_report() -> None:
    assessment = _unsafe_normalization_assessment()
    assert assessment.report.normalization.status.value == "failed"
    assert "semantic projection changed" in (assessment.report.normalization.error or "")


def test_quality_report_records_normalizer_provenance_and_recomputes_key() -> None:
    registry = _registry()
    registry.register_normalizer(SafeMarkdownNormalizer())
    assessment = CandidateAssessmentService(registry).assess(
        context=QualityContext(
            workspace_id="demo",
            run_id="run-1",
            artifact="qa_report",
            source_bundle=_empty_bundle(),
        ),
        content="report  ",
        media_type="text/markdown",
        strategy_names=["generic-artifact-contracts"],
    )

    component = assessment.report.normalization.components[0]
    assert component.name == "safe-markdown-representation"
    assert component.configuration_sha256.startswith("sha256:")
    assert component.operations
    assert assessment.report.normalization.status.value == "applied"
    assert assessment.report.recompute_assessment_key() == assessment.report.assessment_key


def test_quality_report_normalizer_identity_tampering_changes_assessment_key() -> None:
    assessment = _unsafe_normalization_assessment()
    component = assessment.report.normalization.components[0]
    tampered = assessment.report.model_copy(
        update={
            "normalization": assessment.report.normalization.model_copy(
                update={"components": (component.model_copy(update={"version": "9.9.9"}),)}
            )
        }
    )
    assert tampered.recompute_assessment_key() != assessment.report.assessment_key


def test_candidate_bundle_commit_is_create_only_and_idempotent(tmp_path: Path) -> None:
    store, _workspace = _workspace_store(tmp_path)
    bundle = store.create_source_bundle("demo", "run-1")
    context = QualityContext(
        workspace_id="demo",
        run_id="run-1",
        artifact="qa_report",
        source_bundle=bundle,
    )
    service = CandidateAssessmentService(_registry())
    assessment = service.assess(
        context=context,
        content="report",
        media_type="text/markdown",
        strategy_names=["generic-artifact-contracts"],
    )

    candidate, created = store.commit_candidate(
        workspace="demo", run_id="run-1", artifact="qa_report", assessment=assessment
    )
    repeated, repeated_created = store.commit_candidate(
        workspace="demo", run_id="run-1", artifact="qa_report", assessment=assessment
    )

    assert created and not repeated_created
    assert repeated == candidate
    assert not hasattr(candidate, "quality_passed")
    assert (tmp_path / candidate.quality_report_path).is_file()
    assert not list((tmp_path / "workspaces/demo/candidates/run-1/.staging").glob("*"))

    different = service.assess(
        context=context,
        content="different report",
        media_type="text/markdown",
        strategy_names=["generic-artifact-contracts"],
    )
    with pytest.raises(FileExistsError, match="assessment key"):
        store.commit_candidate(
            workspace="demo", run_id="run-1", artifact="qa_report", assessment=different
        )


def test_candidate_restores_evidence_and_partial_status_from_manifest(tmp_path: Path) -> None:
    store, _ = _workspace_store(tmp_path)
    bundle = store.create_source_bundle("demo", "run-1")
    assessment = CandidateAssessmentService(_registry()).assess(
        context=QualityContext(
            workspace_id="demo", run_id="run-1", artifact="qa_report", source_bundle=bundle
        ),
        content="report",
        media_type="text/markdown",
        strategy_names=["generic-artifact-contracts"],
    )
    store.commit_candidate(
        workspace="demo",
        run_id="run-1",
        artifact="qa_report",
        assessment=assessment,
        partial=True,
        evidence=["evidence/a.json"],
    )

    restored = store.load_candidate(workspace="demo", run_id="run-1", artifact="qa_report")

    assert restored is not None
    assert restored.partial is True and restored.status == "partial"
    assert restored.evidence == ["evidence/a.json"]
    assert restored.provenance_complete


def test_candidate_manifest_policy_versions_must_match_report(tmp_path: Path) -> None:
    store, _, candidate = _direct_promotion_fixture(tmp_path)
    manifest_path = tmp_path / candidate.path
    manifest_path = manifest_path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["policy_versions"] = {"tampered": "9"}
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="policy_versions"):
        store.load_candidate(workspace="demo", run_id="run-1", artifact="qa_report")


def test_candidate_manifest_media_type_is_restored(tmp_path: Path) -> None:
    store, _, candidate = _direct_promotion_fixture(tmp_path)
    restored = store.load_candidate(workspace="demo", run_id="run-1", artifact="qa_report")
    assert restored is not None
    assert restored.media_type == "text/markdown"
    assert restored.media_type == candidate.media_type


def test_candidate_load_does_not_require_external_partial_or_evidence(tmp_path: Path) -> None:
    store, _, _ = _direct_promotion_fixture(tmp_path, partial=True)
    restored = store.load_candidate(workspace="demo", run_id="run-1", artifact="qa_report")
    assert restored is not None and restored.partial is True


def test_legacy_incomplete_v2_candidate_is_query_only(tmp_path: Path) -> None:
    store, snapshot, candidate = _direct_promotion_fixture(tmp_path)
    report_path = tmp_path / (candidate.quality_report_path or "")
    legacy_report = {
        "schema_version": "agentic-qa.harness.quality-report.v2",
        "policy_versions": {"generic-artifact-contracts": "3.0.0"},
    }
    report_content = (json.dumps(legacy_report, ensure_ascii=False, indent=2) + "\n").encode()
    report_path.write_bytes(report_content)
    manifest_path = report_path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for field in (
        "workspace_id",
        "run_id",
        "media_type",
        "status",
        "partial",
        "evidence",
        "policy_versions",
        "created_at",
    ):
        manifest.pop(field)
    manifest["files"]["quality-report.json"] = (
        "sha256:" + hashlib.sha256(report_content).hexdigest()
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    restored = store.load_candidate(workspace="demo", run_id="run-1", artifact="qa_report")

    assert restored is not None
    assert restored.status == "provenance_incomplete"
    assert restored.partial is None and restored.evidence is None
    assert not restored.provenance_complete
    snapshot.candidates = [restored]
    with pytest.raises(PermissionError):
        store.promote_many(snapshot, [_approved(restored, ArtifactVariant.RAW)])


def test_candidate_bundle_is_invisible_when_staging_write_fails(
    tmp_path: Path, monkeypatch
) -> None:
    store, _workspace = _workspace_store(tmp_path)
    bundle = store.create_source_bundle("demo", "run-1")
    context = QualityContext(
        workspace_id="demo",
        run_id="run-1",
        artifact="qa_report",
        source_bundle=bundle,
    )
    assessment = CandidateAssessmentService(_registry()).assess(
        context=context,
        content="report",
        media_type="text/markdown",
        strategy_names=["generic-artifact-contracts"],
    )
    original = artifact_repository._write_fsynced
    calls = 0

    def fail_second_write(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fault injection")
        original(path, content)

    monkeypatch.setattr(artifact_repository, "_write_fsynced", fail_second_write)
    with pytest.raises(OSError, match="fault injection"):
        store.commit_candidate(
            workspace="demo", run_id="run-1", artifact="qa_report", assessment=assessment
        )

    candidate_root = tmp_path / "workspaces/demo/candidates/run-1"
    assert not (candidate_root / "qa_report").exists()
    assert not list((candidate_root / ".staging").glob("*"))


def test_concurrent_candidate_commit_has_one_visible_winner(tmp_path: Path) -> None:
    store, _workspace = _workspace_store(tmp_path)
    bundle = store.create_source_bundle("demo", "run-1")
    context = QualityContext(
        workspace_id="demo",
        run_id="run-1",
        artifact="qa_report",
        source_bundle=bundle,
    )
    assessment = CandidateAssessmentService(_registry()).assess(
        context=context,
        content="report",
        media_type="text/markdown",
        strategy_names=["generic-artifact-contracts"],
    )

    def commit() -> bool:
        return store.commit_candidate(
            workspace="demo", run_id="run-1", artifact="qa_report", assessment=assessment
        )[1]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: commit(), range(2)))

    assert sorted(results) == [False, True]
    candidate = store.load_candidate(workspace="demo", run_id="run-1", artifact="qa_report")
    assert candidate is not None


def _direct_promotion_fixture(
    tmp_path: Path, *, blocked: bool = False, normalized: bool = False, partial: bool = False
):
    store, _ = _workspace_store(tmp_path)
    bundle = store.create_source_bundle("demo", "run-1")
    registry = _registry(requires_sources=blocked)
    if normalized:
        registry.register_normalizer(SafeMarkdownNormalizer())
    assessment = CandidateAssessmentService(registry).assess(
        context=QualityContext(
            workspace_id="demo",
            run_id="run-1",
            artifact="qa_report",
            source_bundle=bundle,
        ),
        content="report  " if normalized else "report",
        media_type="text/markdown",
        strategy_names=(
            ["generic-artifact-contracts", "requires-sources"]
            if blocked
            else ["generic-artifact-contracts"]
        ),
    )
    candidate, _ = store.commit_candidate(
        workspace="demo",
        run_id="run-1",
        artifact="qa_report",
        assessment=assessment,
        partial=partial,
    )
    snapshot = RunSnapshot(
        run_id="run-1",
        workspace_id="demo",
        status="partial" if partial else "needs_human_review",
        request=StartRunCommand(workspace_id="demo", goal="test"),
        candidates=[candidate],
    )
    return store, snapshot, candidate


def _approved(candidate: ArtifactCandidate, variant: ArtifactVariant) -> ApprovedArtifactVersion:
    reference = candidate.version_ref(variant)
    version = next(item for item in candidate.versions if item.variant == variant)
    return ApprovedArtifactVersion(**reference.model_dump(), path=version.path)


def _rewrite_candidate_report(tmp_path: Path, candidate: ArtifactCandidate, mutate) -> str:
    report_path = tmp_path / (candidate.quality_report_path or "")
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    mutate(payload)
    content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    report_path.write_bytes(content)
    manifest_path = report_path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report_hash = "sha256:" + hashlib.sha256(content).hexdigest()
    manifest["files"]["quality-report.json"] = report_hash
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report_hash


def test_direct_promote_rejects_blocked_raw_variant(tmp_path: Path) -> None:
    store, snapshot, candidate = _direct_promotion_fixture(tmp_path, blocked=True)
    with pytest.raises(PermissionError, match="未通过质量门"):
        store.promote_many(snapshot, [_approved(candidate, ArtifactVariant.RAW)])


def test_direct_promote_rejects_blocked_normalized_variant(tmp_path: Path) -> None:
    store, snapshot, candidate = _direct_promotion_fixture(tmp_path, blocked=True, normalized=True)
    with pytest.raises(PermissionError, match="未通过质量门"):
        store.promote_many(snapshot, [_approved(candidate, ArtifactVariant.NORMALIZED)])


def test_direct_promote_rejects_partial_candidate(tmp_path: Path) -> None:
    store, snapshot, candidate = _direct_promotion_fixture(tmp_path, partial=True)
    with pytest.raises(PermissionError, match="partial candidate"):
        store.promote_many(snapshot, [_approved(candidate, ArtifactVariant.RAW)])


def test_direct_promote_rejects_report_source_bundle_hash_mismatch(tmp_path: Path) -> None:
    store, snapshot, candidate = _direct_promotion_fixture(tmp_path)
    report_hash = _rewrite_candidate_report(
        tmp_path, candidate, lambda payload: payload.update(source_bundle_hash="sha256:" + "f" * 64)
    )
    reloaded = candidate.model_copy(update={"quality_report_sha256": report_hash})
    snapshot.candidates = [reloaded]
    with pytest.raises(ValueError, match="source bundle hash"):
        store.promote_many(snapshot, [_approved(reloaded, ArtifactVariant.RAW)])


def test_direct_promote_rejects_report_assessment_key_mismatch(tmp_path: Path) -> None:
    store, snapshot, candidate = _direct_promotion_fixture(tmp_path)
    report_hash = _rewrite_candidate_report(
        tmp_path, candidate, lambda payload: payload.update(assessment_key="sha256:" + "f" * 64)
    )
    reloaded = candidate.model_copy(update={"quality_report_sha256": report_hash})
    snapshot.candidates = [reloaded]
    with pytest.raises(ValueError, match="assessment key"):
        store.promote_many(snapshot, [_approved(reloaded, ArtifactVariant.RAW)])


def test_direct_promote_rejects_variant_hash_mismatch(tmp_path: Path) -> None:
    store, snapshot, candidate = _direct_promotion_fixture(tmp_path, normalized=True)

    def mutate(payload):
        payload["variants"][1]["content_sha256"] = "sha256:" + "f" * 64
        payload["normalization"]["normalized_sha256"] = "sha256:" + "f" * 64

    report_hash = _rewrite_candidate_report(tmp_path, candidate, mutate)
    reloaded = candidate.model_copy(update={"quality_report_sha256": report_hash})
    snapshot.candidates = [reloaded]
    with pytest.raises(ValueError, match="hash"):
        store.promote_many(snapshot, [_approved(reloaded, ArtifactVariant.NORMALIZED)])


def _publication_fixture(tmp_path: Path):
    store, snapshot, candidate = _direct_promotion_fixture(tmp_path)
    approved = _approved(candidate, ArtifactVariant.RAW)
    snapshot.status = "published"
    snapshot.review_status = {"qa_report": "confirmed"}
    records = {
        "qa_report": {
            "schema_version": "agentic-qa.harness.review-record.v2",
            "run_id": "run-1",
            "artifact": "qa_report",
            "status": "confirmed",
        }
    }
    return store, snapshot, approved, records


def test_publish_recovers_after_current_file_written(tmp_path: Path, monkeypatch) -> None:
    store, snapshot, approved, records = _publication_fixture(tmp_path)
    original = store.artifacts.promote_many

    def fail_after_promote(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("after current")

    monkeypatch.setattr(store.artifacts, "promote_many", fail_after_promote)
    with pytest.raises(OSError, match="after current"):
        store.publish_review(snapshot, [approved], records)
    monkeypatch.setattr(store.artifacts, "promote_many", original)

    restored = store.load_snapshot("demo", "run-1")
    journal = json.loads(
        (tmp_path / "workspaces/demo/reviews/run-1/publication-intent.json").read_text()
    )
    assert restored.status == "published" and journal["status"] == "committed"


def test_publish_recovers_after_review_record_written(tmp_path: Path, monkeypatch) -> None:
    store, snapshot, approved, records = _publication_fixture(tmp_path)
    original = store.artifacts.write_review

    def fail_after_review(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("after review")

    monkeypatch.setattr(store.artifacts, "write_review", fail_after_review)
    with pytest.raises(OSError, match="after review"):
        store.publish_review(snapshot, [approved], records)
    monkeypatch.setattr(store.artifacts, "write_review", original)
    assert store.load_snapshot("demo", "run-1").status == "published"


def test_publish_does_not_duplicate_history_entry(tmp_path: Path) -> None:
    store, snapshot, approved, records = _publication_fixture(tmp_path)
    store.publish_review(snapshot, [approved], records)
    store.publish_review(snapshot, [approved], records)
    index = (tmp_path / "workspaces/demo/published/qa_report/history/index.yml").read_text()
    assert index.count("run_id: run-1") == 1


def test_publish_journal_committed_only_after_snapshot_saved(tmp_path: Path, monkeypatch) -> None:
    store, snapshot, approved, records = _publication_fixture(tmp_path)
    original = store.runs.save_snapshot
    observed: list[str] = []

    def observe(target):
        journal_path = tmp_path / "workspaces/demo/reviews/run-1/publication-intent.json"
        observed.append(json.loads(journal_path.read_text())["status"])
        original(target)

    monkeypatch.setattr(store.runs, "save_snapshot", observe)
    store.publish_review(snapshot, [approved], records)
    assert observed == ["preparing"]


def test_publish_rolls_back_when_recovery_provenance_is_invalid(
    tmp_path: Path, monkeypatch
) -> None:
    store, snapshot, approved, records = _publication_fixture(tmp_path)
    original = store.artifacts.promote_many

    def fail_after_promote(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("crash after publish")

    monkeypatch.setattr(store.artifacts, "promote_many", fail_after_promote)
    with pytest.raises(OSError, match="crash after publish"):
        store.publish_review(snapshot, [approved], records)
    monkeypatch.setattr(store.artifacts, "promote_many", original)
    (tmp_path / approved.path).write_text("tampered", encoding="utf-8")

    restored = store.load_snapshot("demo", "run-1")
    journal = json.loads(
        (tmp_path / "workspaces/demo/reviews/run-1/publication-intent.json").read_text()
    )
    assert journal["status"] == "rolled_back"
    assert restored.status == "planning"
    assert not (tmp_path / "workspaces/demo/published/qa_report/current.md").exists()


@pytest.mark.skipif(os.name == "nt", reason="创建 symlink 通常需要 Windows 开发者权限")
def test_source_symlink_is_rejected(tmp_path: Path) -> None:
    store, workspace = _workspace_store(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    (workspace / "sources/link.md").symlink_to(outside)

    bundle = store.create_source_bundle("demo", "run-1")

    assert any(issue.code == "source_link_rejected" for issue in bundle.issues)
