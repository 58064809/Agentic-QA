from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from runtime.workflow.builder import build_graph_from_spec
from runtime.workflow.conditions import DEFAULT_CONDITION
from runtime.workflow.loader import load_workflow_spec, load_workflow_spec_by_id

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_WORKFLOW_DIR = REPO_ROOT / "workflows/runtime"
EXPECTED_RUNTIME_WORKFLOWS = {
    "analysis-and-testcases.workflow.yml": ("analysis_and_testcases", "mvp_analysis_testcases"),
    "requirement-analysis.workflow.yml": ("requirement_analysis", "analysis"),
    "testcase-generation.workflow.yml": ("testcase_generation", "testcase_generation"),
}


def runtime_workflow_paths() -> list[Path]:
    return sorted(RUNTIME_WORKFLOW_DIR.glob("*.workflow.yml"))


@pytest.mark.parametrize("workflow_path", runtime_workflow_paths(), ids=lambda path: path.name)
def test_real_runtime_workflow_yaml_loads_and_builds(workflow_path):
    spec = load_workflow_spec(workflow_path)

    assert spec.id
    assert spec.name
    assert spec.version >= 1
    assert spec.source_path == workflow_path.as_posix()
    assert build_graph_from_spec(spec, REPO_ROOT)


def test_real_runtime_workflow_set_is_explicitly_tracked():
    actual = {
        path.name: (load_workflow_spec(path).id, load_workflow_spec(path).state.get("task_type"))
        for path in runtime_workflow_paths()
    }

    assert actual == EXPECTED_RUNTIME_WORKFLOWS


def test_load_real_runtime_workflows_by_id():
    for workflow_id, _task_type in EXPECTED_RUNTIME_WORKFLOWS.values():
        spec = load_workflow_spec_by_id(REPO_ROOT, workflow_id)

        assert spec.id == workflow_id


@pytest.mark.parametrize("workflow_path", runtime_workflow_paths(), ids=lambda path: path.name)
def test_real_runtime_conditional_sources_have_explicit_default(workflow_path):
    spec = load_workflow_spec(workflow_path)
    edges_by_source = defaultdict(list)
    for edge in spec.edges:
        edges_by_source[edge.source].append(edge)

    for edges in edges_by_source.values():
        conditional_edges = [edge for edge in edges if edge.condition]
        if not conditional_edges:
            continue

        assert any(edge.condition == DEFAULT_CONDITION for edge in conditional_edges)
