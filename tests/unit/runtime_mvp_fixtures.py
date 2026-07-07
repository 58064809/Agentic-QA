from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from runtime.workspace import ARTIFACT_SPECS  # noqa: E402


def write_file(path: Path, content: str = "placeholder") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def create_mvp_repo(root: Path) -> Path:
    required_files = {
        "AGENTS.md": "Agent 协作规范",
        "COMMANDS.md": "命令路由",
        "docs/roadmap.md": "Runtime 路线图",
        "workflows/01-requirement-analysis-workflow.md": "需求分析工作流",
        "workflows/10-runtime-testcase-generation-workflow.md": "Runtime 测试用例工作流",
        "workflows/02-testcase-generation-workflow.md": "测试用例工作流",
        "workflows/runtime/analysis-and-testcases.workflow.yml": (
            REPO_ROOT / "workflows/runtime/analysis-and-testcases.workflow.yml"
        ).read_text(encoding="utf-8"),
        "workflows/runtime/requirement-analysis.workflow.yml": (
            REPO_ROOT / "workflows/runtime/requirement-analysis.workflow.yml"
        ).read_text(encoding="utf-8"),
        "workflows/runtime/testcase-generation.workflow.yml": (
            REPO_ROOT / "workflows/runtime/testcase-generation.workflow.yml"
        ).read_text(encoding="utf-8"),
        "workflows/runtime/api-test-draft.workflow.yml": (
            REPO_ROOT / "workflows/runtime/api-test-draft.workflow.yml"
        ).read_text(encoding="utf-8"),
        "workflows/runtime/rag-automation-case.workflow.yml": (
            REPO_ROOT / "workflows/runtime/rag-automation-case.workflow.yml"
        ).read_text(encoding="utf-8"),
        "prompts/requirement-analysis-prompt.md": "需求分析 Prompt",
        "prompts/testcase-design-prompt.md": "测试用例 Prompt",
        "prompts/api-test-generation.md": (REPO_ROOT / "prompts/api-test-generation.md").read_text(
            encoding="utf-8"
        ),
        "prompts/rag-automation-case-prompt.md": (
            REPO_ROOT / "prompts/rag-automation-case-prompt.md"
        ).read_text(encoding="utf-8"),
        "docs/api-test-generation.md": (REPO_ROOT / "docs/api-test-generation.md").read_text(
            encoding="utf-8"
        ),
        "docs/automation-case-generation.md": (
            REPO_ROOT / "docs/automation-case-generation.md"
        ).read_text(encoding="utf-8"),
        "docs/rag-architecture.md": (REPO_ROOT / "docs/rag-architecture.md").read_text(
            encoding="utf-8"
        ),
        "docs/rag-run-record-spec.md": (REPO_ROOT / "docs/rag-run-record-spec.md").read_text(
            encoding="utf-8"
        ),
        "workflows/10-rag-automation-case-generation-workflow.md": (
            REPO_ROOT / "workflows/10-rag-automation-case-generation-workflow.md"
        ).read_text(encoding="utf-8"),
        "rules/requirement-analysis-rules.md": "需求分析规则",
        "rules/testcase-rules.md": "测试用例规则",
        "rules/api-test-rules.md": (REPO_ROOT / "rules/api-test-rules.md").read_text(
            encoding="utf-8"
        ),
        "rules/automation-case-rules.md": (REPO_ROOT / "rules/automation-case-rules.md").read_text(
            encoding="utf-8"
        ),
        "rules/rag-rules.md": (REPO_ROOT / "rules/rag-rules.md").read_text(encoding="utf-8"),
        "rules/source-reference-rules.md": (
            REPO_ROOT / "rules/source-reference-rules.md"
        ).read_text(encoding="utf-8"),
        "rules/review-gate-rules.md": "审核门规则",
        "rules/artifact-path-rules.md": "产物路径规则",
        "skills/registry/skills.yaml": (
            "version: 1\n"
            "required_first_version: true\n"
            "skills:\n"
            "  - id: S1\n    file: skills/core/requirement-understanding-skill.md\n"
            "  - id: S2\n    file: skills/core/context-building-skill.md\n"
            "  - id: S3\n    file: skills/core/rag-retrieval-skill.md\n"
            "  - id: S4\n    file: skills/analysis/test-scope-decomposition-skill.md\n"
            "  - id: S5\n    file: skills/analysis/risk-identification-skill.md\n"
            "  - id: S6\n    file: skills/test-design/test-method-selection-skill.md\n"
            "  - id: S7\n    file: skills/test-design/testcase-generation-skill.md\n"
            "  - id: S8\n    file: skills/test-design/testcase-review-skill.md\n"
            "  - id: S9\n    file: skills/core/output-formatting-skill.md\n"
            "  - id: S10\n    file: skills/knowledge/knowledge-capture-skill.md\n"
        ),
        "skills/core/requirement-understanding-skill.md": "需求理解 Skill",
        "skills/core/context-building-skill.md": "上下文构建 Skill",
        "skills/core/rag-retrieval-skill.md": "RAG 检索 Skill",
        "skills/analysis/test-scope-decomposition-skill.md": "测试范围拆解 Skill",
        "skills/analysis/risk-identification-skill.md": "风险识别 Skill",
        "skills/test-design/test-method-selection-skill.md": "测试方法选择 Skill",
        "skills/test-design/testcase-generation-skill.md": "测试用例生成 Skill",
        "skills/test-design/testcase-review-skill.md": "用例评审 Skill",
        "skills/core/output-formatting-skill.md": "输出格式化 Skill",
        "skills/knowledge/knowledge-capture-skill.md": "知识沉淀 Skill",
        "skills/analysis/requirement-decomposition-skill.md": "需求拆解技能",
        "skills/analysis/business-rule-extraction-skill.md": "业务规则提取技能",
        "knowledge/templates/requirement-analysis-template.md": "需求分析模板",
        "skills/test-design/test-design-skill.md": "测试设计技能",
        "skills/test-design/equivalence-partitioning-skill.md": "等价类技能",
        "skills/test-design/boundary-value-analysis-skill.md": "边界值技能",
        "skills/test-design/scenario-modeling-skill.md": "场景建模技能",
        "skills/test-design/state-transition-modeling-skill.md": "状态迁移技能",
        "skills/test-design/risk-based-testing-skill.md": "风险测试技能",
        "knowledge/templates/testcase-template.md": "测试用例模板",
        "knowledge/automation/yaml-case-schema.md": (
            REPO_ROOT / "knowledge/automation/yaml-case-schema.md"
        ).read_text(encoding="utf-8"),
        "knowledge/automation/assertion-rules.md": (
            REPO_ROOT / "knowledge/automation/assertion-rules.md"
        ).read_text(encoding="utf-8"),
        "knowledge/automation/variable-extraction-rules.md": (
            REPO_ROOT / "knowledge/automation/variable-extraction-rules.md"
        ).read_text(encoding="utf-8"),
        "knowledge/templates/rag-run-record-template.json": (
            REPO_ROOT / "knowledge/templates/rag-run-record-template.json"
        ).read_text(encoding="utf-8"),
        "skills/api-testing.md": (REPO_ROOT / "skills/api-testing.md").read_text(encoding="utf-8"),
        "prd/demo-requirement/metadata.yml": (
            "requirement_id: demo-requirement\n"
            "title: Demo Requirement\n"
            "status: draft\n"
            "created_by: test\n"
            "created_at: '2026-01-01T00:00:00+00:00'\n"
            "updated_at: '2026-01-01T00:00:00+00:00'\n"
            "artifacts: {}\n"
            "reviews: {}\n"
        ),
        "prd/demo-requirement/input/requirement.md": (
            "# 登录需求\n\n"
            "## 背景\n\n用户使用手机号密码登录。\n\n"
            "## 功能范围\n\n"
            "- 用户输入手机号和密码后发起登录。\n"
            "- 登录成功后返回访问 token。\n\n"
            "## 验收标准\n\n"
            "- 正确手机号和正确密码可以登录成功。\n"
            "- token 过期后必须重新登录。\n"
        ),
        "prd/demo-requirement/input/api.md": (
            "# 登录 API\n\n"
            "## POST /api/v1/auth/login\n\n"
            '```json\n{"phone":"13800138000","password":"pwd"}\n```\n'
        ),
    }
    for relative_path, content in required_files.items():
        write_file(root / relative_path, content)
    return root


def count_testcase_rows(markdown: str) -> int:
    rows = 0
    header_seen = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if stripped.startswith("| 标题 |") or stripped.startswith("| 用例ID |"):
            header_seen = True
            continue
        if set(stripped.replace("|", "").strip()) <= {"-", ":"}:
            continue
        if header_seen:
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
        (
            "| 用例ID | 需求/规则来源 | 标题 | 测试类型 | 优先级 | 前置条件 | 测试数据 | "
            "测试步骤 | 预期结果 | 断言/证据 | 待确认项 |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for index, (title, case_priority, precondition, steps, expected) in enumerate(
        rows[:row_count],
        start=1,
    ):
        lines.append(
            f"| TC-{index:03d} | REQ-{index:03d} | {title} | 功能 | {case_priority} | "
            f"{precondition} | 测试数据-{index} | {steps} | {expected} | "
            "检查接口响应、页面提示和数据状态 | 无 |"
        )
    return "\n".join(lines) + "\n"


def write_promote_fixture(
    repo_root: Path,
    *,
    artifact_keys: list[str],
    run_id: str = "run-20260101-000000-promote",
) -> str:
    prd_rel = "prd/demo-requirement"
    run_dir = repo_root / prd_rel / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir = repo_root / ".runtime" / "runs" / run_id
    runtime_dir.mkdir(parents=True, exist_ok=True)

    if len(artifact_keys) == 1:
        key = artifact_keys[0]
        preview = (
            "---\n"
            f"artifact_type: {ARTIFACT_SPECS[key]['artifact_type']}\n"
            "status: needs_human_review\n"
            "human_review_required: true\n"
            "---\n\n"
            f"# {key} candidate\n"
        )
    else:
        sections = [
            "---",
            "artifact_type: artifact_preview",
            "status: needs_human_review",
            "human_review_required: true",
            "---",
            "",
            "# 候选产物预览",
            "",
        ]
        for key in artifact_keys:
            sections.extend(
                [
                    f"<!-- artifact:start {key} -->",
                    "",
                    "---",
                    f"artifact_type: {ARTIFACT_SPECS[key]['artifact_type']}",
                    "status: needs_human_review",
                    "human_review_required: true",
                    "---",
                    "",
                    f"# {key} candidate",
                    "",
                    f"<!-- artifact:end {key} -->",
                    "",
                ]
            )
        preview = "\n".join(sections)

    preview_rel = f"{prd_rel}/runs/{run_id}/artifact-preview.md"
    (repo_root / preview_rel).write_text(preview, encoding="utf-8")
    (repo_root / prd_rel / "runs/latest.yml").write_text(
        yaml.safe_dump({"run_id": run_id}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    result = {
        "prd_path": prd_rel,
        "run_id": run_id,
        "run_status": "interrupted",
        "review_status": "needs_human_review",
        "output_paths": {key: preview_rel for key in artifact_keys},
        "draft_artifacts": {key: f"# {key} candidate\n" for key in artifact_keys},
        "artifacts": [{"name": key} for key in artifact_keys],
    }
    (runtime_dir / "run-state.json").write_text(
        json.dumps({"result": result}, ensure_ascii=False),
        encoding="utf-8",
    )
    for key in artifact_keys:
        review_path = repo_root / prd_rel / ARTIFACT_SPECS[key]["review_path"]
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(
            yaml.safe_dump(
                {
                    "artifact": ARTIFACT_SPECS[key]["current_path"],
                    "artifact_type": ARTIFACT_SPECS[key]["artifact_type"],
                    "status": "approved",
                    "decision": "approve",
                    "run_id": run_id,
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    return run_id
