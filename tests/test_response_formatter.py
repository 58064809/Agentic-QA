from runtime.response_formatter import format_requirement_analysis
from runtime.response_formatter import format_script_generation
from runtime.response_formatter import format_test_cases


def test_format_requirement_analysis_summary_is_limited() -> None:
    result = {
        "analysis_basis": {
            "requirement_docs": ["docs/report_prd.md"],
            "prototype_assets": ["prototype/report.png"],
        },
        "business_objects": [f"业务对象{i}" for i in range(1, 12)],
        "requirement_items": [f"需求项{i}" for i in range(1, 25)],
        "business_rules": ["导出完成后必须生成下载链接"],
        "test_focus": ["验证需求项：导出完成后必须生成下载链接"],
        "risk_list": ["如果约束未实现，下载链路不可用"],
        "open_questions": ["是否支持重复导出"],
        "acceptance_criteria": ["系统行为与需求一致"],
        "next_actions": ["补齐重复导出规则"],
    }

    output = format_requirement_analysis(result)

    assert "# 需求分析结论" in output
    assert "8、业务对象8" in output
    assert "业务对象9" not in output
    assert "已保存到完整 Markdown 文件" in output


def test_format_requirement_analysis_full_has_no_truncation_hint() -> None:
    result = {
        "analysis_basis": {"requirement_docs": ["docs/report_prd.md"], "prototype_assets": []},
        "requirement_items": [f"需求项{i}" for i in range(1, 25)],
        "business_objects": [],
        "business_rules": [],
        "test_focus": [],
        "risk_list": [],
        "open_questions": [],
        "acceptance_criteria": [],
        "next_actions": [],
    }

    output = format_requirement_analysis(result, full=True)

    assert "24、需求项24" in output
    assert "已保存到完整 Markdown 文件" not in output
    assert "完整内容见 JSON" not in output


def test_format_test_cases_includes_markdown_table() -> None:
    output = format_test_cases(
        {
            "analysis_basis": {"requirement_docs": ["docs/a.md"], "prototype_assets": []},
            "generation_strategy": ["按风险生成"],
            "case_groups": ["主流程"],
            "open_questions": [],
            "case_count": 1,
            "columns": ["用例ID", "用例标题", "优先级"],
            "cases": [{"用例ID": "REQ-001", "用例标题": "主流程", "优先级": "P1"}],
        }
    )

    assert "# 测试用例" in output
    assert "共 1 条" in output
    assert "| 用例ID | 用例标题 | 优先级 |" in output


def test_format_test_cases_summary_limits_table() -> None:
    output = format_test_cases(
        {
            "analysis_basis": {"requirement_docs": ["docs/a.md"], "prototype_assets": []},
            "generation_strategy": [],
            "case_groups": [],
            "open_questions": [],
            "case_count": 13,
            "columns": ["用例ID", "用例标题"],
            "cases": [{"用例ID": f"REQ-{index:03d}", "用例标题": f"用例{index}"} for index in range(1, 14)],
        }
    )

    assert "REQ-012" in output
    assert "REQ-013" not in output
    assert "已保存到完整 Markdown 文件" in output


def test_format_script_generation_includes_python_block() -> None:
    output = format_script_generation(
        {
            "analysis_basis": {"requirement_docs": [], "prototype_assets": []},
            "open_questions": [],
            "recommended_file_name": "test_generated.py",
            "script_content": "def test_demo():\n    assert True\n",
        }
    )

    assert "# pytest 脚本草稿" in output
    assert "test_generated.py" in output
    assert "```python" in output
    assert "def test_demo" in output
