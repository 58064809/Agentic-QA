from __future__ import annotations

import json

from runtime_fixtures import build_valid_testcases, count_testcase_rows, create_runtime_repo

from runtime.graph.app import (
    run_requirement_analysis_workflow,
    run_testcase_generation_workflow,
)
from runtime.graph.nodes import artifact_generation
from runtime.llm.openai_compatible import OpenAICompatibleAdapter


def test_review_grade_analysis_quality_rejects_old_section_skeleton(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)

    monkeypatch.setattr(
        artifact_generation,
        "render_requirement_analysis_skeleton",
        lambda state: (
            """---
status: needs_human_review
artifact_type: requirement_analysis
human_review_required: true
---

# 需求分析草稿

## 需求概述
## 业务规则
## 流程拆解
## 角色与权限
## 数据与状态
## 异常与边界
## 风险点
## 待确认问题
"""
        ),
    )

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert not result.success
    assert any("需求背景与目标" in error for error in result.quality_errors)
    assert any("需求到测试覆盖映射" in error for error in result.quality_errors)


def test_review_grade_analysis_rejects_empty_pending_questions(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)

    monkeypatch.setattr(
        artifact_generation,
        "render_requirement_analysis_skeleton",
        lambda state: (
            """---
status: needs_human_review
artifact_type: requirement_analysis
human_review_required: true
---

# 需求分析草稿

## 1. 需求背景与目标
- 目标：拆解业务需求。
## 2. 业务范围
- 范围内：主流程。
## 3. 角色与权限
- 业务用户和后台角色。
## 4. 主流程拆解
1. 发起请求。
## 5. 分支流程与异常流程
- 异常输入被拒绝。
## 6. 业务规则清单
| 编号 | 规则 | 来源 | 状态 |
|---|---|---|---|
| R01 | 主流程必须校验权限 | PRD | needs_human_review |
## 7. 数据字段与状态流转
- 状态从创建到完成。
## 8. 接口与依赖系统
- 依赖目标接口。
## 9. 测试范围建议
- P0 覆盖主流程。
## 10. 风险点与影响面
| 风险点 | 影响面 | 建议处理 |
|---|---|---|
| 权限不清 | 越权 | 补充角色矩阵 |
## 11. 待确认问题

## 12. 需求到测试覆盖映射
| 需求/规则 | 测试覆盖建议 | 优先级 |
|---|---|---|
| 主流程 | 成功和失败 | P0 |
"""
        ),
    )

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert not result.success
    assert any("待确认问题少于 3 个" in error for error in result.quality_errors)


def test_review_grade_testcase_quality_rejects_short_placeholder_table(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)

    monkeypatch.setattr(
        artifact_generation,
        "render_testcase_skeleton",
        lambda state: (
            """---
status: needs_human_review
artifact_type: testcases
human_review_required: true
---

# 测试用例草稿

| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|
| 主流程验证 | P0 | 待确认账号和数据 | 1. 按主流程操作 | 结果符合需求 |
"""
        ),
    )

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert not result.success
    assert any("少于 15 条" in error for error in result.quality_errors)
    assert any("占位内容" in error for error in result.quality_errors)


def test_review_grade_testcase_rejects_type_column(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)
    valid = build_valid_testcases()
    invalid = valid.replace(
        "| 用例ID | 需求/规则来源 | 标题 | 测试类型 | 优先级 | 前置条件 | 测试数据 | "
        "测试步骤 | 预期结果 | 断言/证据 | 待确认项 |",
        "| 用例ID | 需求/规则来源 | 标题 | 用例类型 | 测试类型 | 优先级 | 前置条件 | "
        "测试数据 | 测试步骤 | 预期结果 | 断言/证据 | 待确认项 |",
    ).replace(
        "| TC-001 | REQ-001 | 主流程成功处理 | 功能 | P0 |",
        "| TC-001 | REQ-001 | 主流程成功处理 | 主流程 | 功能 | P0 |",
    )
    monkeypatch.setattr(artifact_generation, "render_testcase_skeleton", lambda state: invalid)

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert not result.success
    assert any("用例类型" in error for error in result.quality_errors)
    assert any("严格等于富用例 11 列" in error for error in result.quality_errors)


def test_review_grade_testcase_rejects_invalid_priority(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)
    invalid = build_valid_testcases().replace(
        "| TC-002 | REQ-002 | 异常输入被拒绝 | 功能 | P1 |",
        "| TC-002 | REQ-002 | 异常输入被拒绝 | 功能 | P4 |",
    )
    monkeypatch.setattr(artifact_generation, "render_testcase_skeleton", lambda state: invalid)

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert not result.success
    assert any("非法优先级: P4" in error for error in result.quality_errors)


def test_review_grade_testcase_rejects_empty_coverage_matrix(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)
    invalid = build_valid_testcases() + "\n## 覆盖矩阵\n\n"
    monkeypatch.setattr(artifact_generation, "render_testcase_skeleton", lambda state: invalid)

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        use_llm=False,
        record_run=False,
    )

    assert not result.success
    assert any("覆盖矩阵必须包含表头和至少一条有效映射" in error for error in result.quality_errors)


def test_llm_generated_review_grade_testcases_pass_quality_gate(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-secret")
    monkeypatch.setattr(
        OpenAICompatibleAdapter,
        "generate_text",
        lambda self, prompt: build_valid_testcases(row_count=15),
    )

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        use_llm=True,
        record_run=False,
    )

    assert result.success
    assert result.llm["used"] is True
    assert count_testcase_rows(result.draft_artifacts["testcases"]) == 15


def test_llm_prompt_uses_configured_max_and_compacts_image_links(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)
    requirement = repo_root / "prd/demo-requirement/input/requirement.md"
    requirement.write_text(
        requirement.read_text(encoding="utf-8")
        + "\n![原型图](https://internal-api-drive-stream.feishu.cn/space/image/demo.png)\n",
        encoding="utf-8",
    )
    captured_prompts: list[str] = []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-secret")
    monkeypatch.setenv("DEEPSEEK_MAX_INPUT_CHARS", "64000")

    def fake_generate(self, prompt: str) -> str:
        captured_prompts.append(prompt)
        return build_valid_testcases(row_count=15)

    monkeypatch.setattr(OpenAICompatibleAdapter, "generate_text", fake_generate)

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        use_llm=True,
        record_run=False,
    )

    assert result.success
    assert result.llm["max_input_chars"] == 64000
    assert captured_prompts
    assert "internal-api-drive-stream.feishu.cn" not in captured_prompts[0]
    assert "图片引用已省略" in captured_prompts[0]


def test_llm_testcases_allow_repeated_table_header(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-secret")
    valid = build_valid_testcases(row_count=15)
    rich_header = (
        "| 用例ID | 需求/规则来源 | 标题 | 测试类型 | 优先级 | 前置条件 | 测试数据 | "
        "测试步骤 | 预期结果 | 断言/证据 | 待确认项 |"
    )
    duplicated_header = valid.replace(
        "| TC-004 | REQ-004 | 权限不足不能操作 | 功能 | P0 |",
        f"{rich_header}\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
        "| TC-004 | REQ-004 | 权限不足不能操作 | 功能 | P0 |",
        1,
    )
    monkeypatch.setattr(
        OpenAICompatibleAdapter,
        "generate_text",
        lambda self, prompt: duplicated_header,
    )

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        use_llm=True,
        record_run=False,
    )

    assert result.success
    assert not any("非法优先级" in error for error in result.quality_errors)
    assert result.llm["used"] is True


def test_llm_invalid_testcases_fallback_to_skeleton(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-secret")
    monkeypatch.setattr(
        OpenAICompatibleAdapter,
        "generate_text",
        lambda self, prompt: (
            """---
status: needs_human_review
artifact_type: testcases
human_review_required: true
---

# 测试用例草稿

| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|
| 占位 | 优先级 | 占位 | TODO | 占位 |
"""
        ),
    )

    result = run_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        use_llm=True,
        record_run=False,
    )

    assert result.success
    assert result.llm["used"] is True
    assert result.llm["testcase_quality_fallback_used"] is True
    assert any("LLM 测试用例草稿未通过质量门" in warning for warning in result.warnings)
    assert not result.quality_errors
    assert count_testcase_rows(result.draft_artifacts["testcases"]) >= 15


def test_use_llm_without_api_key_degrades_to_skeleton(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        use_llm=True,
        record_run=False,
    )

    assert result.success
    assert result.llm["enabled"] is True
    assert result.llm["used"] is False
    assert result.llm["calls"] == 0
    assert any("已降级为 Skeleton 生成" in warning for warning in result.warnings)


def test_run_record_does_not_store_llm_secret(tmp_path, monkeypatch):
    repo_root = create_runtime_repo(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-token-should-not-be-stored")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "demo-model")
    monkeypatch.setattr(
        OpenAICompatibleAdapter,
        "generate_text",
        lambda self, prompt: (
            """---
status: needs_human_review
artifact_type: requirement_analysis
human_review_required: true
---

# 需求分析草稿

## 1. 需求背景与目标
## 2. 业务范围
## 3. 角色与权限
## 4. 主流程拆解
## 5. 分支流程与异常流程
## 6. 业务规则清单
## 7. 数据字段与状态流转
## 8. 接口与依赖系统
## 9. 测试范围建议
## 10. 风险点与影响面
## 11. 待确认问题
## 12. 需求到测试覆盖映射
"""
        ),
    )

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        use_llm=True,
    )

    assert result.run_summary_json is not None
    summary_text = (repo_root / result.run_summary_json).read_text(encoding="utf-8")
    summary = json.loads(summary_text)
    assert "secret-token-should-not-be-stored" not in summary_text
    assert "api_key" not in summary_text
    assert summary["llm"]["base_url"] == "https://example.test/v1"
    assert summary["llm"]["model"] == "demo-model"
    assert summary["llm"]["calls"] == 1
