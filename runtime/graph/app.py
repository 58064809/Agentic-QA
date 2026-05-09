from __future__ import annotations

from pathlib import Path

from runtime.graph.nodes.artifact_writer import artifact_writer_node
from runtime.graph.nodes.context_loader import context_loader_node
from runtime.graph.nodes.human_review import human_review_node
from runtime.graph.nodes.intent_router import intent_router_node
from runtime.graph.nodes.metadata_update import metadata_update_node
from runtime.graph.nodes.quality_checker import testcase_quality_check_node
from runtime.graph.nodes.testcase_generation import testcase_generation_node
from runtime.graph.nodes.workflow_selector import workflow_selector_node
from runtime.graph.state import QAWorkflowState
from runtime.schemas.runtime_result import RuntimeResult


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_testcase_generation_workflow(
    user_input: str,
    prd_path: Path | str,
    *,
    repo_root: Path | None = None,
    approve_write: bool = False,
) -> RuntimeResult:
    root = (repo_root or default_repo_root()).resolve()
    state = QAWorkflowState(
        user_input=user_input,
        prd_path=Path(prd_path).as_posix(),
        dry_run=not approve_write,
        approve_write=approve_write,
    )

    nodes = [
        lambda current: intent_router_node(current),
        lambda current: workflow_selector_node(current, root),
        lambda current: context_loader_node(current, root),
        lambda current: testcase_generation_node(current),
        lambda current: testcase_quality_check_node(current, root),
        lambda current: human_review_node(current),
        lambda current: artifact_writer_node(current, root),
        lambda current: metadata_update_node(current),
    ]

    for node in nodes:
        node(state)

    return RuntimeResult.from_state(state)
