from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from harness import (
    CreateWorkspaceCommand,
    ExecutionProfile,
    Harness,
    PlanTask,
    QAPlan,
    StartRunCommand,
)
from harness.contracts import SkillManifest
from harness.infrastructure.manifests.registry import AgentRegistry, SkillRegistry, ToolRegistry
from harness.testing.evals import recorded_model_gateway


def test_start_run_command_rejects_legacy_prd_path() -> None:
    with pytest.raises(ValidationError, match="旧工作区不受 Harness 支持"):
        StartRunCommand(workspace_id="prd/demo", goal="test")


def test_start_run_command_rejects_likely_secrets_before_run_persistence() -> None:
    with pytest.raises(ValidationError, match="likely secret"):
        StartRunCommand(workspace_id="demo", goal="test with API_KEY=abcdefgh")


def test_workspace_accepts_safe_unicode_name_with_spaces(tmp_path: Path) -> None:
    harness = Harness(tmp_path, model_gateway=recorded_model_gateway())
    name = "城市开局计划 H5 规则"

    workspace = harness.create_workspace(CreateWorkspaceCommand(workspace_id=name))
    request = StartRunCommand(workspace_id=name, goal="test")

    assert workspace == tmp_path / "workspaces" / name
    assert request.workspace_id == name


@pytest.mark.parametrize("name", ["../escape", "a/b", "a\\b", "CON", "bad:name", "trail."])
def test_workspace_rejects_unsafe_directory_name(name: str) -> None:
    with pytest.raises(ValidationError, match="安全目录名"):
        StartRunCommand(workspace_id=name, goal="test")


def test_workspace_rejects_duplicate_quality_policies() -> None:
    with pytest.raises(ValidationError, match="cannot contain duplicates"):
        CreateWorkspaceCommand(
            workspace_id="demo",
            quality_policies=["city-opening-rewards", "city-opening-rewards"],
        )


@pytest.mark.parametrize("environment", ["prod", "production", "eu-live"])
def test_execution_profile_rejects_production_like_environments(environment: str) -> None:
    with pytest.raises(ValidationError, match="production-like"):
        ExecutionProfile(environment=environment)


def test_analysis_only_profile_cannot_enable_ui_mutations() -> None:
    with pytest.raises(ValidationError, match="analysis-only"):
        ExecutionProfile(allow_ui_mutations=True)


def test_plan_rejects_cycles() -> None:
    with pytest.raises(ValidationError, match="dependency cycle"):
        QAPlan(
            tasks=[
                PlanTask(id="a", objective="a", agent="test_designer", dependencies=["b"]),
                PlanTask(id="b", objective="b", agent="test_designer", dependencies=["a"]),
            ]
        )


def test_builtin_manifests_are_declarative_and_complete() -> None:
    tools = ToolRegistry.builtin()
    skills = SkillRegistry.builtin()
    agents = AgentRegistry.builtin(skills=skills, tools=tools)
    assert {item.name for item in agents.list()} == {
        "qa_supervisor",
        "requirement_analyst",
        "risk_strategist",
        "test_designer",
        "api_test_engineer",
        "ui_test_engineer",
        "test_executor",
        "failure_triager",
        "qa_reporter",
        "review_assistant",
    }
    assert "artifact.promote" in {item.name for item in tools.list()}
    assert "artifact.promote" not in agents.get("review_assistant").tool_allowlist
    for agent in agents.list():
        for skill in agent.skills:
            assert skills.get(skill).name == skill


def test_builtin_skill_knowledge_is_compiled_into_instructions() -> None:
    skills = SkillRegistry.builtin()

    instructions = skills.instructions("test-design")

    assert "等价类" in instructions
    assert "边界值" in instructions
    assert "API" in instructions
    assert skills.get("test-design").references == [
        "test-design.md",
        "assertion-design.md",
    ]


def test_skill_knowledge_reference_cannot_escape_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("do not load", encoding="utf-8")
    manifest = SkillManifest(
        name="unsafe",
        description="unsafe reference",
        instructions="base",
        references=["../outside.md"],
    )

    with pytest.raises(ValueError, match="escapes package"):
        SkillRegistry({"unsafe": manifest}, knowledge_root=tmp_path / "knowledge")


def test_skill_knowledge_reference_must_exist(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    manifest = SkillManifest(
        name="missing",
        description="missing reference",
        instructions="base",
        references=["missing.md"],
    )

    with pytest.raises(ValueError, match="is missing"):
        SkillRegistry({"missing": manifest}, knowledge_root=knowledge)
