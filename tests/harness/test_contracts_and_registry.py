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
from harness.contracts import AgentManifest, SkillManifest
from harness.domain.models import (
    KnowledgeSpec,
    PromptInstruction,
    SkillPromptManifest,
)
from harness.infrastructure.manifests.registry import (
    AgentRegistry,
    KnowledgeRegistry,
    PhasePromptRegistry,
    SkillRegistry,
    ToolRegistry,
)
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


def test_public_v2_manifest_contracts_remain_unchanged() -> None:
    agent = AgentManifest(name="sample", role="sample", prompt="sample")
    skill = SkillManifest(
        name="sample",
        description="sample",
        instructions="sample",
        references=["sample.md"],
    )

    assert agent.schema_version == "agentic-qa.harness.agent-manifest.v2"
    assert skill.schema_version == "agentic-qa.harness.skill-manifest.v2"


def test_builtin_skill_knowledge_is_structured_and_referenced() -> None:
    skills = SkillRegistry.builtin()

    knowledge = skills.knowledge_for("test-design")

    assert {item.name for item in knowledge} == {"test-design", "assertion-design"}
    assert any("等价类" in step for item in knowledge for step in item.procedure)
    assert skills.get("test-design").knowledge_refs == [
        "test-design",
        "assertion-design",
    ]


def test_skill_knowledge_reference_must_exist() -> None:
    manifest = SkillPromptManifest(
        name="missing",
        description="missing reference",
        instructions=[PromptInstruction(id="skill.missing.base", kind="guidance", text="base")],
        knowledge_refs=["missing"],
    )

    with pytest.raises(KeyError, match="unknown knowledge"):
        SkillRegistry({"missing": manifest}, knowledge=KnowledgeRegistry({}))


def test_skill_knowledge_must_apply_to_referencing_skill() -> None:
    manifest = SkillPromptManifest(
        name="consumer",
        description="consumer",
        instructions=[PromptInstruction(id="skill.consumer.base", kind="guidance", text="base")],
        knowledge_refs=["shared"],
    )
    knowledge = KnowledgeSpec(
        name="shared",
        version="1.0.0",
        purpose="shared",
        applies_to=["different-skill"],
        inputs=["input"],
        procedure=["step"],
        output_expectations=["output"],
        evidence_policy=["evidence"],
        uncertainty_policy=["unknown"],
        prohibited_actions=["prohibited"],
        deterministic_checks=["validator:test"],
    )

    with pytest.raises(ValueError, match="does not apply"):
        SkillRegistry(
            {"consumer": manifest},
            knowledge=KnowledgeRegistry({"shared": knowledge}),
        )


def test_contract_and_safety_instructions_require_deterministic_enforcement() -> None:
    with pytest.raises(ValidationError, match="requires enforced_by"):
        PromptInstruction(id="test.contract", kind="contract", text="contract")
    with pytest.raises(ValidationError, match="unknown deterministic enforcement"):
        PromptInstruction(
            id="test.contract",
            kind="contract",
            text="contract",
            enforced_by=["prompt:itself"],
        )


def test_builtin_prompt_phases_reference_registered_agents() -> None:
    agents = AgentRegistry.builtin()
    phases = PhasePromptRegistry.builtin()

    for phase in phases.list():
        for agent in phase.agents:
            assert agents.get(agent).name == agent
