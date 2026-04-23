from pathlib import Path

from actions.analyze_requirement import analyze_requirement
from actions.generate_test_cases import generate_test_cases
from actions.generate_test_script import generate_test_script
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


def test_generate_test_script_returns_pytest_skeleton() -> None:
    result = generate_test_script("根据需求生成脚本", _sample_requirement_context())

    assert result["task"] == "script_generation"
    assert result["script_framework"] == "pytest"
    assert "class TestGeneratedFromRequirement" in result["script_content"]
    assert "导出完成后必须生成下载链接" in result["script_content"]


def test_search_logs_finds_matches_in_explicit_file(tmp_path: Path) -> None:
    log_file = tmp_path / "app.log"
    log_file.write_text("INFO start\nERROR timeout while calling service\nINFO done\n", encoding="utf-8")

    result = search_logs(file_path=str(log_file), keyword="timeout")

    assert result["task"] == "log_analysis"
    assert result["match_count"] == 1
    assert any("timeout while calling service" in match for match in result["matches"])
