"""Unit tests for artifact_promoter utility functions."""

from __future__ import annotations

import pytest

from runtime.graph.nodes.artifact_promoter import (
    _artifact_keys_for_task,
    _extract_marked_preview,
    _preview_content_for_key,
)
from runtime.graph.state import QAWorkflowState


def _state(task_type: str) -> QAWorkflowState:
    return QAWorkflowState(user_input="test", prd_path="prd/test", task_type=task_type)


def test_analysis_keys():
    assert _artifact_keys_for_task(_state("analysis")) == ["requirement_analysis"]


def test_testcase_keys():
    assert _artifact_keys_for_task(_state("testcase_generation")) == ["testcases"]


def test_mvp_keys():
    keys = _artifact_keys_for_task(_state("mvp_analysis_testcases"))
    assert keys == ["requirement_analysis", "testcases"]


def test_empty_keys():
    keys = _artifact_keys_for_task(_state(""))
    assert "requirement_analysis" in keys
    assert "testcases" in keys


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


def test_preview_multi_missing():
    with pytest.raises(ValueError):
        _preview_content_for_key("no match", "x", ["a", "b"])
