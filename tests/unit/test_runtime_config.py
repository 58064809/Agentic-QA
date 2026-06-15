from __future__ import annotations

from pathlib import Path

import pytest

import runtime.cli as cli
from runtime.config import load_app_config
from runtime.graph.nodes.workflow_selector import workflow_selector_node
from runtime.graph.state import QAWorkflowState


def write_file(path: Path, content: str = "placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_load_app_config_merges_tracked_and_local_files(tmp_path: Path) -> None:
    write_file(
        tmp_path / "configs/config.yaml",
        """
workflow:
  default_workflow_files:
    - workflows/default.md
rag:
  enabled: false
  top_k: 3
""",
    )
    write_file(
        tmp_path / "configs/local.yaml",
        """
rag:
  enabled: true
  use_llm_api_key: false
""",
    )

    config = load_app_config(tmp_path)

    assert config.workflow.default_workflow_files == ["workflows/default.md"]
    assert config.llm.enabled is True
    assert config.rag["enabled"] is True
    assert config.rag["top_k"] == 3
    assert config.rag["use_llm_api_key"] is False


def test_load_app_config_reads_llm_and_workflow_use_llm(tmp_path: Path) -> None:
    write_file(
        tmp_path / "configs/config.yaml",
        """
llm:
  enabled: false
  semantic_router_enabled: false
workflow:
  use_llm:
    requirement_analysis: false
    testcase_generation: true
    mvp_analysis_testcases: false
""",
    )

    config = load_app_config(tmp_path)

    assert config.llm.enabled is False
    assert config.llm.semantic_router_enabled is False
    assert config.workflow.use_llm_for("requirement_analysis") is False
    assert config.workflow.use_llm_for("testcase_generation") is True
    assert config.workflow.use_llm_for("unknown") is True


def test_load_app_config_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    write_file(tmp_path / "configs/config.yaml", "- not\n- mapping\n")

    with pytest.raises(ValueError, match="配置文件必须是 YAML mapping"):
        load_app_config(tmp_path)


def test_workflow_selector_uses_configured_workflow_files(tmp_path: Path) -> None:
    write_file(
        tmp_path / "configs/config.yaml",
        """
workflow:
  intent_workflow_files:
    testcase_generation:
      - workflows/custom-testcase.md
""",
    )
    write_file(tmp_path / "workflows/custom-testcase.md")
    state = QAWorkflowState(
        user_input="请生成测试用例",
        prd_path="prd/demo",
        intent="testcase_generation",
    )

    workflow_selector_node(state, tmp_path)

    assert state.workflow_files == ["workflows/custom-testcase.md"]
    assert not state.errors


def test_cli_run_workflow_uses_configured_llm_switches(tmp_path: Path, monkeypatch) -> None:
    write_file(
        tmp_path / "configs/config.yaml",
        """
workflow:
  use_llm:
    requirement_analysis: false
    testcase_generation: true
    mvp_analysis_testcases: false
""",
    )
    calls: list[tuple[str, bool]] = []

    def fake_requirement(**kwargs):
        calls.append(("requirement_analysis", kwargs["use_llm"]))
        return object()

    def fake_testcase(**kwargs):
        calls.append(("testcase_generation", kwargs["use_llm"]))
        return object()

    def fake_mvp(**kwargs):
        calls.append(("mvp_analysis_testcases", kwargs["use_llm"]))
        return object()

    monkeypatch.setattr(cli, "run_requirement_analysis_workflow", fake_requirement)
    monkeypatch.setattr(cli, "run_mvp_testcase_generation_workflow", fake_testcase)
    monkeypatch.setattr(cli, "run_mvp_analysis_and_testcases_workflow", fake_mvp)

    cli._run_workflow(
        "分析",
        "prd/demo",
        intent="requirement_analysis",
        repo_root=tmp_path,
        session=object(),  # type: ignore[arg-type]
    )
    cli._run_workflow(
        "用例",
        "prd/demo",
        intent="testcase_generation",
        repo_root=tmp_path,
        session=object(),  # type: ignore[arg-type]
    )
    cli._run_workflow(
        "全部",
        "prd/demo",
        intent="mvp",
        repo_root=tmp_path,
        session=object(),  # type: ignore[arg-type]
    )

    assert calls == [
        ("requirement_analysis", False),
        ("testcase_generation", True),
        ("mvp_analysis_testcases", False),
    ]


def test_cli_global_llm_disabled_overrides_workflow_switch(tmp_path: Path, monkeypatch) -> None:
    write_file(
        tmp_path / "configs/config.yaml",
        """
llm:
  enabled: false
workflow:
  use_llm:
    testcase_generation: true
""",
    )
    calls: list[bool] = []

    def fake_testcase(**kwargs):
        calls.append(kwargs["use_llm"])
        return object()

    monkeypatch.setattr(cli, "run_mvp_testcase_generation_workflow", fake_testcase)

    cli._run_workflow(
        "用例",
        "prd/demo",
        intent="testcase_generation",
        repo_root=tmp_path,
        session=object(),  # type: ignore[arg-type]
    )

    assert calls == [False]


def test_cli_route_user_intent_respects_semantic_router_switch(tmp_path: Path) -> None:
    write_file(
        tmp_path / "configs/config.yaml",
        """
llm:
  enabled: true
  semantic_router_enabled: false
""",
    )

    route = cli._route_user_intent("帮我分析 prd/demo", tmp_path)

    assert route.intent == "requirement_analysis"
    assert "配置已禁用 LLM 语义路由" in route.summary
