from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.graph.mvp_graph import (  # noqa: E402
    run_mvp_analysis_and_testcases_workflow,
    run_mvp_testcase_generation_workflow,
    run_requirement_analysis_workflow,
)
from runtime.graph.nodes import mvp_generation  # noqa: E402
from runtime.llm.openai_compatible import OpenAICompatibleAdapter  # noqa: E402


def write_file(path: Path, content: str = "placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_mvp_repo(root: Path) -> Path:
    required_files = {
        "AGENTS.md": "Agent 协作规范",
        "COMMANDS.md": "命令路由",
        "docs/architecture/production-agent-runtime-roadmap.md": "Runtime 路线图",
        "workflows/01-requirement-analysis-workflow.md": "需求分析工作流",
        "workflows/10-runtime-testcase-generation-workflow.md": "Runtime 测试用例工作流",
        "workflows/02-testcase-generation-workflow.md": "测试用例工作流",
        "prompts/requirement-analysis-prompt.md": "需求分析 Prompt",
        "prompts/testcase-design-prompt.md": "测试用例 Prompt",
        "rules/requirement-analysis-rules.md": "需求分析规则",
        "rules/testcase-rules.md": "测试用例规则",
        "rules/review-gate-rules.md": "审核门规则",
        "rules/artifact-path-rules.md": "产物路径规则",
        "skills/requirement-decomposition-skill.md": "需求拆解技能",
        "skills/business-rule-extraction-skill.md": "业务规则提取技能",
        "knowledge/templates/requirement-analysis-template.md": "需求分析模板",
        "skills/test-design-skill.md": "测试设计技能",
        "skills/equivalence-partitioning-skill.md": "等价类技能",
        "skills/boundary-value-analysis-skill.md": "边界值技能",
        "skills/scenario-modeling-skill.md": "场景建模技能",
        "skills/state-transition-modeling-skill.md": "状态迁移技能",
        "skills/risk-based-testing-skill.md": "风险测试技能",
        "knowledge/templates/testcase-template.md": "测试用例模板",
        "prd/demo-requirement/metadata.yml": "id: demo-requirement\n",
        "prd/demo-requirement/requirement.md": (
            "# 登录需求\n\n"
            "## 背景\n\n用户使用手机号密码登录。\n\n"
            "## 功能范围\n\n"
            "- 用户输入手机号和密码后发起登录。\n"
            "- 登录成功后返回访问 token。\n\n"
            "## 验收标准\n\n"
            "- 正确手机号和正确密码可以登录成功。\n"
            "- token 过期后必须重新登录。\n"
        ),
        "prd/demo-requirement/api-doc.md": (
            "# 登录 API\n\n"
            "## POST /api/v1/auth/login\n\n"
            "```json\n{\"phone\":\"13800138000\",\"password\":\"pwd\"}\n```\n"
        ),
    }
    for relative_path, content in required_files.items():
        write_file(root / relative_path, content)
    return root


def count_testcase_rows(markdown: str) -> int:
    rows = 0
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| 标题 |"):
            continue
        if set(stripped.replace("|", "").strip()) <= {"-", ":"}:
            continue
        rows += 1
    return rows


def build_valid_testcases(row_count: int = 15, *, priority: str = "P1") -> str:
    base_rows = [
        (
            "主流程成功处理",
            "P0",
            "账号有效且具备权限",
            "1. 提交主流程请求",
            "接口和页面均显示成功，状态已更新",
        ),
        (
            "异常输入被拒绝",
            "P1",
            "账号有效，准备错误数据",
            "1. 输入错误格式<br>2. 提交",
            "接口返回参数错误，数据不落库",
        ),
        (
            "边界值按规则处理",
            "P1",
            "已确认边界值",
            "1. 提交边界内外数据",
            "边界外被拒绝，边界内按规则处理",
        ),
        (
            "权限不足不能操作",
            "P0",
            "使用无权限角色账号",
            "1. 调用目标接口",
            "接口拒绝访问并记录权限日志",
        ),
        (
            "状态已完成后不能重复流转",
            "P1",
            "数据状态为已完成",
            "1. 再次提交操作",
            "状态不变，返回状态不允许",
        ),
        (
            "重复提交保持幂等",
            "P1",
            "准备可提交数据",
            "1. 连续提交两次",
            "只处理一次，数据库无重复记录",
        ),
        (
            "数据一致性校验",
            "P1",
            "准备关联数据",
            "1. 提交操作<br>2. 查询数据库",
            "页面、接口和数据库字段一致",
        ),
        (
            "历史数据兼容展示",
            "P2",
            "准备老数据或历史状态",
            "1. 打开详情页",
            "历史数据可展示，不报错",
        ),
        ("接口超时可恢复", "P2", "模拟接口超时", "1. 提交请求", "返回可识别提示，状态未脏写"),
        (
            "日志审计完整记录",
            "P2",
            "日志开关开启",
            "1. 触发成功和失败",
            "日志和审计记录完整且不含敏感明文",
        ),
        (
            "回归影响范围验证",
            "P1",
            "准备关联业务数据",
            "1. 执行主流程<br>2. 检查关联功能",
            "关联功能不受异常影响",
        ),
    ]
    rows = list(base_rows)
    while len(rows) < row_count:
        rows.append(
            (
                f"补充分支流程场景 {len(rows) + 1}",
                priority,
                "账号有效，准备分支流程数据",
                "1. 执行业务分支<br>2. 检查接口响应",
                "接口、页面、状态和日志符合需求",
            )
        )

    lines = [
        "---",
        "status: needs_human_review",
        "artifact_type: testcase_draft",
        "human_review_required: true",
        "---",
        "",
        "# 测试用例草稿",
        "",
        "| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |",
        "|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {title} | {case_priority} | {precondition} | {steps} | {expected} |"
        for title, case_priority, precondition, steps, expected in rows[:row_count]
    )
    return "\n".join(lines) + "\n"


def test_analyze_dry_run_generates_analysis_without_writing(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    assert result.task_type == "analysis"
    assert result.run_status == "completed"
    assert result.review_status == "needs_human_review"
    assert "requirement_analysis" in result.draft_artifacts
    analysis = result.draft_artifacts["requirement_analysis"]
    assert "needs_human_review" in analysis
    assert "## 1. 需求背景与目标" in analysis
    assert "## 12. 需求到测试覆盖映射" in analysis
    assert "Runtime MVP Skeleton" not in analysis
    assert not (repo_root / "prd/demo-requirement/10-analysis/requirement-analysis.md").exists()


def test_analyze_approve_write_creates_analysis_draft(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_requirement_analysis_workflow(
        "请分析这个需求",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    output_path = repo_root / "prd/demo-requirement/10-analysis/requirement-analysis.md"
    assert result.success
    assert output_path.exists()
    structured_json = output_path.with_suffix(".json")
    structured_yaml = output_path.with_suffix(".yml")
    assert structured_json.exists()
    assert structured_yaml.exists()
    structured = json.loads(structured_json.read_text(encoding="utf-8"))
    assert structured["schema_version"] == "agentic-qa.artifact.v1"
    assert structured["markdown_path"] == "prd/demo-requirement/10-analysis/requirement-analysis.md"
    assert result.wrote_file
    assert result.review_status == "write_approved"
    assert "artifact_type: requirement_analysis" in output_path.read_text(encoding="utf-8")


def test_generate_testcases_dry_run_generates_testcases_without_writing(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    assert result.task_type == "testcase_generation"
    assert result.run_status == "completed"
    assert result.review_status == "needs_human_review"
    assert "testcases" in result.draft_artifacts
    testcases = result.draft_artifacts["testcases"]
    assert "| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |" in testcases
    assert count_testcase_rows(testcases) >= 15
    assert "用例类型" not in testcases.splitlines()[10:20]
    assert not (repo_root / "prd/demo-requirement/20-testcases/testcases.md").exists()


def test_generate_testcases_approve_write_creates_testcase_draft(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    output_path = repo_root / "prd/demo-requirement/20-testcases/testcases.md"
    assert result.success
    assert result.wrote_file
    assert result.review_status == "write_approved"
    assert "artifact_type: testcase_draft" in output_path.read_text(encoding="utf-8")


def test_mvp_dry_run_generates_two_drafts_without_writing(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert result.success
    assert result.task_type == "mvp_analysis_testcases"
    assert result.run_status == "completed"
    assert result.review_status == "needs_human_review"
    assert set(result.draft_artifacts) == {"requirement_analysis", "testcases"}
    assert "## 12. 需求到测试覆盖映射" in result.draft_artifacts["requirement_analysis"]
    assert count_testcase_rows(result.draft_artifacts["testcases"]) >= 15
    assert not (repo_root / "prd/demo-requirement/10-analysis/requirement-analysis.md").exists()
    assert not (repo_root / "prd/demo-requirement/20-testcases/testcases.md").exists()


def test_mvp_approve_write_creates_analysis_and_testcases(tmp_path):
    repo_root = create_mvp_repo(tmp_path)

    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    assert result.success
    assert result.wrote_file
    assert result.review_status == "write_approved"
    assert (repo_root / "prd/demo-requirement/10-analysis/requirement-analysis.md").is_file()
    assert (repo_root / "prd/demo-requirement/20-testcases/testcases.md").is_file()


def test_mvp_approve_write_refuses_partial_overwrite(tmp_path):
    repo_root = create_mvp_repo(tmp_path)
    existing_analysis = repo_root / "prd/demo-requirement/10-analysis/requirement-analysis.md"
    write_file(existing_analysis, "人工已有分析")

    result = run_mvp_analysis_and_testcases_workflow(
        "请分析需求并生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        approve_write=True,
    )
    assert not result.success
    assert not result.wrote_file
    assert existing_analysis.read_text(encoding="utf-8") == "人工已有分析"
    assert not (repo_root / "prd/demo-requirement/20-testcases/testcases.md").exists()
    assert any("本次未写入任何产物" in error for error in result.errors)


def test_review_grade_analysis_quality_rejects_old_section_skeleton(tmp_path, monkeypatch):
    repo_root = create_mvp_repo(tmp_path)

    monkeypatch.setattr(
        mvp_generation,
        "render_requirement_analysis_skeleton",
        lambda state: """---
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
""",
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
    repo_root = create_mvp_repo(tmp_path)

    monkeypatch.setattr(
        mvp_generation,
        "render_requirement_analysis_skeleton",
        lambda state: """---
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
""",
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
    repo_root = create_mvp_repo(tmp_path)

    monkeypatch.setattr(
        mvp_generation,
        "render_testcase_skeleton",
        lambda state: """---
status: needs_human_review
artifact_type: testcase_draft
human_review_required: true
---

# 测试用例草稿

| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |
|---|---|---|---|---|
| 主流程验证 | P0 | 待确认账号和数据 | 1. 按主流程操作 | 结果符合需求 |
""",
    )

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert not result.success
    assert any("少于 15 条" in error for error in result.quality_errors)
    assert any("占位内容" in error for error in result.quality_errors)


def test_review_grade_testcase_rejects_type_column(tmp_path, monkeypatch):
    repo_root = create_mvp_repo(tmp_path)
    valid = build_valid_testcases()
    invalid = valid.replace(
        "| 标题 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |",
        "| 标题 | 用例类型 | 优先级 | 前置条件 | 测试步骤 | 预期结果 |",
    ).replace(
        "| 主流程成功处理 | P0 |",
        "| 主流程成功处理 | 主流程 | P0 |",
    )
    monkeypatch.setattr(mvp_generation, "render_testcase_skeleton", lambda state: invalid)

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert not result.success
    assert any("用例类型" in error for error in result.quality_errors)
    assert any("严格等于固定 5 列" in error for error in result.quality_errors)


def test_review_grade_testcase_rejects_invalid_priority(tmp_path, monkeypatch):
    repo_root = create_mvp_repo(tmp_path)
    invalid = build_valid_testcases().replace(
        "| 异常输入被拒绝 | P1 |",
        "| 异常输入被拒绝 | P4 |",
    )
    monkeypatch.setattr(mvp_generation, "render_testcase_skeleton", lambda state: invalid)

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        record_run=False,
    )

    assert not result.success
    assert any("非法优先级: P4" in error for error in result.quality_errors)


def test_llm_generated_review_grade_testcases_pass_quality_gate(tmp_path, monkeypatch):
    repo_root = create_mvp_repo(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-secret")
    monkeypatch.setattr(
        OpenAICompatibleAdapter,
        "generate_text",
        lambda self, prompt: build_valid_testcases(row_count=15),
    )

    result = run_mvp_testcase_generation_workflow(
        "请生成测试用例",
        "prd/demo-requirement",
        repo_root=repo_root,
        use_llm=True,
        record_run=False,
    )

    assert result.success
    assert result.llm["used"] is True
    assert count_testcase_rows(result.draft_artifacts["testcases"]) == 15


def test_use_llm_without_api_key_degrades_to_skeleton(tmp_path, monkeypatch):
    repo_root = create_mvp_repo(tmp_path)
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
    repo_root = create_mvp_repo(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-token-should-not-be-stored")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "demo-model")
    monkeypatch.setattr(
        OpenAICompatibleAdapter,
        "generate_text",
        lambda self, prompt: """---
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
""",
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
