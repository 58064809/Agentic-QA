from pathlib import Path
from types import SimpleNamespace

from actions.analyze_requirement import analyze_requirement
from actions.analyze_pytest_result import analyze_pytest_result
from actions.generate_test_cases import generate_test_cases
from actions.generate_test_script import generate_test_script
from actions.run_pytest import run_pytest
from actions.search_logs import search_logs


def _sample_requirement_context() -> dict:
    return {
        "selected_requirement_docs": [
            {
                "path": "docs/report_prd.md",
                "content": "# 报表导出\n\n- 导出完成后必须生成下载链接\n- 如果超时，需要提示用户稍后重试\n- 是否支持重复导出？\n",
            }
        ],
        "selected_prototypes": [{"path": "prototype/report.png"}],
        "missing_context": [],
    }


def test_analyze_requirement_uses_discovered_documents() -> None:
    result = analyze_requirement("帮我分析需求", _sample_requirement_context())

    assert result["task"] == "requirement_analysis"
    assert "导出完成后必须生成下载链接" in result["business_rules"]
    assert "是否支持重复导出" in result["open_questions"]
    assert result["analysis_basis"]["prototype_assets"] == ["prototype/report.png"]


def test_analyze_requirement_builds_test_model_for_funds_requirement() -> None:
    context = {
        "requirement_package": {"name": "deposit-management", "relative_root": "requirements/deposit-management"},
        "selected_requirement_docs": [
            {
                "path": "requirements/deposit-management/docs/deposit.md",
                "content": """
# 保证金 PRD

| 角色 | 权限范围 |
|------|----------|
| 财务专员 | 审核网银转账、处理退款、查看财务明细 |

#### 缴纳保证金
- 商家缴纳或补缴保证金，仅支持网银转账方式。
- 应缴总金额按照基础保证金和风险保证金两者金额就高原则计算。
- 上传凭证后状态为待审核，财务审核通过后更新余额，审核失败允许重新上传凭证。
- 冻结金额会影响可用金额和待缴金额。
""",
            }
        ],
        "selected_prototypes": [
            {
                "path": "requirements/deposit-management/prototype/merchant-settlement-deposit.html",
                "size_bytes": 0,
            }
        ],
        "missing_context": [],
    }

    result = analyze_requirement("帮我分析保证金需求", context)

    assert any("保证金账户" in item for item in result["business_objects"])
    assert any("财务专员" in item for item in result["roles_permissions"])
    assert any("应缴总金额" in item for item in result["funds_model"])
    assert any("缴纳凭证状态" in item for item in result["state_model"])
    assert any("P0" in result["priority_test_focus"] for _ in [0])
    assert any("0 字节原型文件" in item for item in result["open_questions"])


def test_generate_test_cases_returns_markdown_table() -> None:
    result = generate_test_cases("帮我生成测试用例", _sample_requirement_context())

    assert result["task"] == "test_case_generation"
    assert result["case_count"] >= 1
    assert "| 用例ID | 模块 | 优先级 | 用例标题 | 前置条件 | 测试数据 | 测试步骤 | 预期结果 | 校验点 | 需求来源 |" in result["markdown_table"]
    assert "导出完成后必须生成下载链接" in result["markdown_table"]
    assert result["automation_guidance"]["automation_candidate_rules"]


def test_generate_test_script_returns_pytest_skeleton() -> None:
    result = generate_test_script("根据需求生成脚本", _sample_requirement_context())

    assert result["task"] == "script_generation"
    assert result["script_framework"] == "pytest"
    assert "class TestGeneratedFromRequirement" in result["script_content"]
    assert "导出完成后必须生成下载链接" in result["script_content"]


def test_generate_test_script_returns_api_skeleton_when_requested() -> None:
    result = generate_test_script("根据需求生成 API 接口自动化脚本", _sample_requirement_context())

    assert result["script_framework"] == "pytest-api"
    assert result["recommended_file_name"].endswith(".py")
    assert "api_client" in result["script_content"]
    assert result["automation_checklist"]


def test_generate_test_script_returns_playwright_skeleton_when_requested() -> None:
    result = generate_test_script("根据需求生成 Playwright E2E 页面自动化脚本", _sample_requirement_context())

    assert result["script_framework"] == "playwright"
    assert result["recommended_file_name"].endswith(".spec.ts")
    assert "test.step" in result["script_content"]
    assert result["script_language"] == "typescript"


def test_search_logs_finds_matches_in_explicit_file(tmp_path: Path) -> None:
    log_file = tmp_path / "app.log"
    log_file.write_text("INFO start\nERROR timeout while calling service\nINFO done\n", encoding="utf-8")

    result = search_logs(file_path=str(log_file), keyword="timeout")

    assert result["task"] == "log_analysis"
    assert result["match_count"] == 1
    assert any("timeout while calling service" in match for match in result["matches"])


def test_run_pytest_returns_protocol_fields(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")

    result = run_pytest(target="tests/test_demo.py", workspace_root=str(tmp_path))

    assert result["_ok"] is True
    assert result["exit_code"] == 0
    assert result["duration_seconds"] >= 0
    assert result["command_args"][0] == "pytest"


def test_run_pytest_decodes_windows_gbk_output(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=b"\xc8\xa8\xcf\xde", stderr=b"")

    monkeypatch.setattr("actions.run_pytest.subprocess.run", fake_run)

    result = run_pytest(target="tests/test_demo.py")

    assert "\u6743\u9650" in result["stdout"]


def test_analyze_pytest_result_extracts_failure_evidence() -> None:
    result = analyze_pytest_result(
        """
FAILED tests/test_demo.py::test_demo - AssertionError: assert 1 == 2
tests/test_demo.py:2: AssertionError
=================== 1 failed in 0.10s ===================
"""
    )

    assert result["_ok"] is False
    assert result["error_type"] == "assertion_error"
    assert result["confidence"] >= 0.8
    assert result["failure_locations"]


def test_analyze_pytest_result_detects_skipped_only() -> None:
    result = analyze_pytest_result("============================= 20 skipped in 0.11s =============================")

    assert result["error_type"] == "skipped_only"
    assert result["confidence"] >= 0.9
    assert result["next_actions"]


def test_analyze_pytest_result_adds_flaky_signals_for_timeout() -> None:
    result = analyze_pytest_result("E TimeoutError: waiting for locator timed out after retry")

    assert result["error_type"] == "timeout"
    assert result["flaky_signals"]
