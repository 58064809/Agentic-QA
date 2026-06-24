from __future__ import annotations

import pytest

from runtime.workflow.catalog import DEFAULT_WORKFLOW_REGISTRY
from runtime.workflow.runner import workflow_id_for_task_type


def test_registered_workflows_cover_runtime_task_types():
    assert DEFAULT_WORKFLOW_REGISTRY.registered_task_types() == {
        "analysis",
        "mvp_analysis_testcases",
        "testcase_generation",
    }
    assert DEFAULT_WORKFLOW_REGISTRY.registered_workflow_ids() == {
        "analysis_and_testcases",
        "requirement_analysis",
        "testcase_generation",
    }


def test_workflow_selection_is_registry_lookup():
    for task_type in DEFAULT_WORKFLOW_REGISTRY.registered_task_types():
        expected = DEFAULT_WORKFLOW_REGISTRY.workflow_id_for_task_type(task_type)

        assert workflow_id_for_task_type(task_type) == expected


def test_unknown_task_type_is_rejected_by_registry():
    with pytest.raises(ValueError, match="task_type"):
        workflow_id_for_task_type("unknown")
