"""Unit tests for artifact_promoter utility functions."""

from __future__ import annotations

import pytest

from runtime.graph.nodes.artifact_promoter import (
    _artifact_keys_for_task,
    _extract_marked_preview,
    _preview_content_for_key,
    _promoted_front_matter,
    promote_artifacts,
)
from runtime.graph.state import QAWorkflowState


def _state(task_type: str) -> QAWorkflowState:
    return QAWorkflowState(user_input="test", prd_path="prd/test", task_type=task_type)


def test_analysis_keys():
    assert _artifact_keys_for_task(_state("analysis")) == ["requirement_analysis"]


def test_testcase_keys():
    assert _artifact_keys_for_task(_state("testcase_generation")) == ["testcases"]


def test_api_test_draft_keys():
    assert _artifact_keys_for_task(_state("api_test_draft")) == ["api_test_draft"]


def test_mvp_keys():
    keys = _artifact_keys_for_task(_state("mvp_analysis_testcases"))
    assert keys == ["requirement_analysis", "testcases"]


def test_empty_keys():
    keys = _artifact_keys_for_task(_state(""))
    assert "requirement_analysis" in keys
    assert "testcases" in keys
    assert "api_test_draft" in keys


def test_marked_preview_extract():
    preview = "p\n<!-- artifact:start k -->\nc\n<!-- artifact:end k -->\ns"
    result = _extract_marked_preview(preview, "k")
    assert result is not None
    assert "c" in result


def test_marked_preview_missing():
    assert _extract_marked_preview("no marker", "x") is None


def test_preview_single_key():
    assert _preview_content_for_key("full\n", "only", ["only"]) == "full\n"


def test_preview_multi_marked():
    preview = (
        "<!-- artifact:start a -->\nA\n<!-- artifact:end a -->\n"
        + "<!-- artifact:start b -->\nB\n<!-- artifact:end b -->"
    )
    result = _preview_content_for_key(preview, "a", ["a", "b"])
    assert result is not None
    assert "A" in result
    assert "B" not in result


def test_preview_single_target_still_extracts_marked_section():
    preview = (
        "# 候选产物预览\n\n"
        "<!-- artifact:start requirement_analysis -->\n\n"
        "## 需求分析候选\n\n"
        "---\nstatus: needs_human_review\nartifact_type: requirement_analysis\n"
        "human_review_required: true\n---\n\n"
        "# 需求分析草稿\n\nanalysis only\n"
        "<!-- artifact:end requirement_analysis -->\n\n"
        "<!-- artifact:start testcases -->\n\n"
        "## 测试用例候选\n\n# 测试用例草稿\n\n| 用例ID |\n"
        "<!-- artifact:end testcases -->\n"
    )

    result = _preview_content_for_key(preview, "requirement_analysis", ["requirement_analysis"])

    assert result.startswith("---")
    assert "需求分析候选" not in result
    assert "测试用例候选" not in result
    assert "| 用例ID |" not in result
    assert "analysis only" in result


def test_promoted_front_matter_marks_formal_artifact():
    content = (
        "---\nstatus: needs_human_review\nartifact_type: testcases\n"
        "human_review_required: true\n---\n\n# 测试用例草稿\n"
    )

    result = _promoted_front_matter(
        content,
        key="testcases",
        version="v1",
        promoted_at="2026-01-01T00:00:00+00:00",
        run_id="run-1",
    )

    assert "status: confirmed" in result
    assert "human_review_required: false" in result
    assert "promoted_from_run: run-1" in result
    assert "current_version: v1" in result


def test_preview_multi_missing():
    with pytest.raises(ValueError):
        _preview_content_for_key("no match", "x", ["a", "b"])


def test_promote_requires_approved_review_even_when_preview_exists(tmp_path):
    repo_root = tmp_path
    preview_path = repo_root / "prd/demo/runs/run-1/artifact-preview.md"
    preview_path.parent.mkdir(parents=True)
    preview_path.write_text("# candidate\n", encoding="utf-8")

    promoted = promote_artifacts(
        "prd/demo",
        "run-1",
        repo_root=repo_root,
        task_type="testcase_generation",
    )

    assert not promoted.success
    assert any("approved" in error for error in promoted.errors)
    assert not (repo_root / "prd/demo/artifacts/testcases.md").exists()
