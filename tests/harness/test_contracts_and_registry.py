from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from harness import PlanTask, QAPlan, TaskRequest
from harness.contracts import SkillManifest
from harness.registry import AgentRegistry, SkillRegistry, ToolRegistry


def test_task_request_rejects_legacy_prd_path() -> None:
    with pytest.raises(ValidationError, match="旧工作区不受 Harness 支持"):
        TaskRequest(workspace="prd/demo", goal="test")


def test_plan_rejects_cycles() -> None:
    with pytest.raises(ValidationError, match="dependency cycle"):
        QAPlan(
            tasks=[
                PlanTask(id="a", objective="a", agent="test_designer", dependencies=["b"]),
                PlanTask(id="b", objective="b", agent="test_designer", dependencies=["a"]),
            ]
        )


def test_builtin_manifests_are_declarative_and_complete() -> None:
    agents = AgentRegistry.builtin()
    skills = SkillRegistry.builtin()
    tools = ToolRegistry.builtin()
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
    assert "API：" in instructions
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
