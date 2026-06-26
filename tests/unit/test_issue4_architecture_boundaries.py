from __future__ import annotations

from pathlib import Path

from runtime.intent import route_user_intent
from runtime.review.state_machine import validate_promote_transition, validate_review_transition
from runtime.workflow.catalog import DEFAULT_WORKFLOW_REGISTRY
from runtime.workflow.runner import workflow_id_for_task_type

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_phase0_baseline_core_directories_and_entries_exist():
    for relative_path in [
        "runtime",
        "docs",
        "rag",
        "workflows",
        "README.md",
        "AGENTS.md",
        "COMMANDS.md",
        "runtime/cli.py",
        "runtime/graph/app.py",
    ]:
        assert (REPO_ROOT / relative_path).exists(), relative_path


def test_core_layers_are_explicit_modules():
    assert callable(route_user_intent)
    assert DEFAULT_WORKFLOW_REGISTRY.registered_workflow_ids() >= {
        "analysis_and_testcases",
        "requirement_analysis",
        "testcase_generation",
    }
    assert callable(validate_review_transition)
    assert callable(validate_promote_transition)
    assert (REPO_ROOT / "rag/manager.py").is_file()


def test_workflow_selection_uses_registry_lookup():
    assert workflow_id_for_task_type("analysis") == "requirement_analysis"
    assert workflow_id_for_task_type("testcase_generation") == "testcase_generation"
    assert workflow_id_for_task_type("mvp_analysis_testcases") == "analysis_and_testcases"


def test_legacy_hardcoded_graph_path_is_removed():
    removed_paths = [
        "runtime/graph/langgraph_app.py",
        "runtime/graph/nodes/intent_router.py",
        "runtime/graph/nodes/workflow_selector.py",
        "runtime/graph/nodes/context_loader.py",
        "runtime/graph/nodes/artifact_generator.py",
        "runtime/graph/nodes/artifact_writer.py",
        "runtime/graph/nodes/quality_checker.py",
        "tests/unit/test_runtime_langgraph.py",
        "tests/unit/test_runtime_skeleton.py",
    ]

    for relative_path in removed_paths:
        assert not (REPO_ROOT / relative_path).exists(), relative_path


def test_cli_declares_natural_language_and_debug_modes_without_absolute_claims():
    cli_text = (REPO_ROOT / "runtime/cli.py").read_text(encoding="utf-8")
    commands_text = (REPO_ROOT / "COMMANDS.md").read_text(encoding="utf-8")

    assert "自然语言模式是主入口" in cli_text
    assert "工程命令用于本地调试" in cli_text
    assert "无子命令、无参数" not in cli_text
    assert "natural language mode" in commands_text
    assert "debug mode" in commands_text
