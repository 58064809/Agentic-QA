from __future__ import annotations

import pytest

from runtime.workflow.catalog import DEFAULT_WORKFLOW_REGISTRY
from runtime.workflow.runner import workflow_id_for_task_type


def test_registered_workflows_cover_runtime_task_types():
    assert DEFAULT_WORKFLOW_REGISTRY.registered_task_types() == {
        "analysis",
        "api_discovery_report",
        "api_test_draft",
        "mvp_analysis_testcases",
        "qa_report",
        "rag_automation_case_generation",
        "testcase_generation",
        "ui_test_draft",
    }
    assert DEFAULT_WORKFLOW_REGISTRY.registered_workflow_ids() == {
        "api_discovery_report",
        "analysis_and_testcases",
        "api_test_draft",
        "requirement_analysis",
        "qa_report",
        "rag_automation_case_generation",
        "testcase_generation",
        "ui_test_draft",
    }


def test_workflow_selection_is_registry_lookup():
    for task_type in DEFAULT_WORKFLOW_REGISTRY.registered_task_types():
        expected = DEFAULT_WORKFLOW_REGISTRY.workflow_id_for_task_type(task_type)

        assert workflow_id_for_task_type(task_type) == expected


def test_unknown_task_type_is_rejected_by_registry():
    with pytest.raises(ValueError, match="task_type"):
        workflow_id_for_task_type("unknown")
