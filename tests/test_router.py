from pathlib import Path

from runtime.intent_matcher import match_intent
from runtime.router import build_log_analysis_kwargs
from runtime.router import build_test_execution_kwargs
from runtime.router import handle_user_input


def test_build_test_execution_kwargs_with_path_marker_and_keyword() -> None:
    kwargs = build_test_execution_kwargs(
        "执行 pytest tests/test_sample.py::test_smoke_path -m smoke -k smoke_path"
    )

    assert kwargs["target"] == "tests/test_sample.py::test_smoke_path"
    assert kwargs["marker"] == "smoke"
    assert kwargs["keyword"] == "smoke_path"


def test_build_test_execution_kwargs_with_requirement_tests_path() -> None:
    kwargs = build_test_execution_kwargs("执行 pytest requirements/deposit-management/tests")

    assert kwargs["target"] == "requirements/deposit-management/tests"


def test_match_test_workflow_execution_intent() -> None:
    assert match_intent("generate cases and run deposit requirement") == "test_workflow_execution"


def test_handle_user_input_returns_clarification_for_ambiguous_intent(tmp_path: Path) -> None:
    result = handle_user_input("帮我处理一下 pytest", workspace_root=tmp_path)

    assert result["ok"] is False
    assert result["error"] == "intent_needs_clarification"
    assert result["candidate_intents"]
    assert result["clarification_prompt"]


def test_build_log_analysis_kwargs_extracts_file_and_keyword() -> None:
    kwargs = build_log_analysis_kwargs(r'分析 "logs/app.log" 关键字 timeout')

    assert kwargs["file_path"] == "logs/app.log"
    assert kwargs["keyword"] == "timeout"


def test_handle_requirement_analysis_saves_output(tmp_path: Path) -> None:
    docs_dir = tmp_path / "requirements"
    prototype_dir = tmp_path / "design"
    docs_dir.mkdir()
    prototype_dir.mkdir()

    (docs_dir / "export_prd.md").write_text(
        "# 导出报表\n\n- 导出成功后必须生成下载链接\n- 如果超时，需要提示用户稍后重试\n",
        encoding="utf-8",
    )
    (prototype_dir / "export.html").write_text("<html>export prototype</html>", encoding="utf-8")

    result = handle_user_input("帮我分析导出报表需求，看看 PRD", workspace_root=tmp_path)

    assert result["ok"] is True
    assert result["intent"] == "requirement_analysis"
    assert result["loaded_resources"]["agent"]["loaded"] is True
    assert result["loaded_resources"]["rule"]["loaded"] is True
    assert result["loaded_resources"]["skill"]["loaded"] is True
    assert result["flow_run"]["executed_steps"]
    assert any(step["step"] == "discover_requirement_context" for step in result["flow_run"]["executed_steps"])
    assert result["requirement_context"]["selected_requirement_docs"]
    assert result["skill_result"]["analysis_basis"]["requirement_docs"]
    assert result["action_result"]["ok"] is True
    assert result["formatted_output"]
    assert result["saved_output"]["files"]

    saved_path = Path(result["saved_output"]["files"][0]["path"])
    assert saved_path.exists()
    assert saved_path.parent == tmp_path / "outputs" / "requirement_analysis"
    assert saved_path.read_text(encoding="utf-8") == result["saved_formatted_output"]
    assert "完整内容见 JSON" not in saved_path.read_text(encoding="utf-8")


def test_handle_requirement_analysis_saves_into_requirement_package(tmp_path: Path) -> None:
    package = tmp_path / "requirements" / "deposit-management"
    docs_dir = package / "docs"
    prototype_dir = package / "prototype"
    docs_dir.mkdir(parents=True)
    prototype_dir.mkdir()

    (docs_dir / "deposit_prd.md").write_text(
        "# 保证金 PRD\n\n- 商家缴纳保证金后必须更新余额\n",
        encoding="utf-8",
    )
    (prototype_dir / "merchant-settlement-deposit.html").write_text("<html>deposit</html>", encoding="utf-8")

    result = handle_user_input("帮我分析保证金需求", workspace_root=tmp_path)

    assert result["ok"] is True
    assert result["requirement_context"]["requirement_package"]["name"] == "deposit-management"
    saved_path = Path(result["saved_output"]["files"][0]["path"])
    assert saved_path.exists()
    assert saved_path.parent == package / "outputs" / "requirement_analysis"


def test_handle_log_analysis_uses_workspace_root_and_saves_output(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    (logs_dir / "app.log").write_text("INFO start\nERROR timeout while calling service\n", encoding="utf-8")

    result = handle_user_input("分析日志 logs/app.log 关键字 timeout", workspace_root=tmp_path)

    assert result["ok"] is True
    assert result["intent"] == "log_analysis"
    assert result["skill_result"]["match_count"] == 1
    assert "timeout while calling service" in result["formatted_output"]
    assert Path(result["saved_output"]["files"][0]["path"]).exists()


def test_handle_test_execution_uses_workspace_root_and_saves_output(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_demo.py").write_text(
        "def test_demo():\n    assert 1 == 1\n",
        encoding="utf-8",
    )

    result = handle_user_input("执行 pytest tests/test_demo.py", workspace_root=tmp_path)

    assert result["ok"] is True
    assert result["intent"] == "test_execution"
    assert result["skill_result"]["exit_code"] == 0
    assert result["skill_result"]["cwd"] == str(tmp_path)
    assert result["skill_result"]["duration_seconds"] >= 0
    assert result["analysis_result"]["confidence"] > 0
    assert any(step["step"] == "run_pytest" for step in result["flow_run"]["executed_steps"])
    assert result["formatted_output"]
    saved_path = Path(result["saved_output"]["files"][0]["path"])
    assert saved_path.exists()
    assert saved_path.parent == tmp_path / "outputs" / "test_reports"


def test_handle_test_execution_saves_into_requirement_package_when_target_is_package_scoped(tmp_path: Path) -> None:
    package = tmp_path / "requirements" / "deposit-management"
    tests_dir = package / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_demo.py").write_text(
        "def test_demo():\n    assert 1 == 1\n",
        encoding="utf-8",
    )

    result = handle_user_input("执行 pytest requirements/deposit-management/tests", workspace_root=tmp_path)

    assert result["ok"] is True
    saved_path = Path(result["saved_output"]["files"][0]["path"])
    assert saved_path.exists()
    assert saved_path.parent == package / "outputs" / "test_reports"


def test_handle_test_workflow_execution_creates_artifacts(tmp_path: Path) -> None:
    package = tmp_path / "requirements" / "deposit-management"
    docs_dir = package / "docs"
    prototype_dir = package / "prototype"
    docs_dir.mkdir(parents=True)
    prototype_dir.mkdir()

    (docs_dir / "deposit_prd.md").write_text(
        "# 保证金 PRD\n\n- 商家缴纳保证金后必须更新余额\n",
        encoding="utf-8",
    )
    (prototype_dir / "deposit.html").write_text("<html>deposit</html>", encoding="utf-8")

    result = handle_user_input("generate cases and run deposit requirement", workspace_root=tmp_path)

    assert result["ok"] is True
    assert result["intent"] == "test_workflow_execution"
    assert result["skill_result"]["case_count"] >= 1
    assert result["skill_result"]["pending_binding_count"] >= 1
    assert result["skill_result"]["analysis_result"]["error_type"] == "skipped_only"
    assert Path(result["skill_result"]["artifacts"]["env_profile"]).exists()
    assert Path(result["skill_result"]["artifacts"]["test_data"]).exists()
    assert Path(result["skill_result"]["artifacts"]["binding_overrides"]).exists()
    assert Path(result["skill_result"]["artifacts"]["execution_plan"]).exists()
    assert Path(result["skill_result"]["artifacts"]["pytest_script"]).exists()
    assert Path(result["skill_result"]["artifacts"]["junit_xml"]).exists()
    saved_path = Path(result["saved_output"]["files"][0]["path"])
    assert saved_path.exists()
    assert saved_path.parent == package / "outputs" / "test_execution"
