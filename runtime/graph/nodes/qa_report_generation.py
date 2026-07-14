from __future__ import annotations

import re
from pathlib import Path

from runtime.graph.nodes.artifact_generation import (
    _build_rag_context,
    _generate_with_optional_llm,
    _path_content,
    _prd_prefix,
    _render_source_files,
    _upsert_artifact,
)
from runtime.graph.nodes.workflow_context import TASK_QA_REPORT
from runtime.graph.state import QAWorkflowState
from runtime.llm.prompt_builder import build_report_prompt
from runtime.workspace import is_run_candidate_markdown_path, resolve_prd_path

REQUIRED_QA_REPORT_SECTIONS = [
    "基本信息",
    "产物索引",
    "测试范围",
    "执行概况",
    "缺陷和风险",
    "未覆盖范围",
    "结论草稿",
    "待人工确认项",
]
EXECUTION_RESULT_PATTERNS = [
    re.compile(r"通过率\s*[:：]\s*(?!待确认|未执行|无执行结果)\d", re.IGNORECASE),
    re.compile(r"(全部通过|零缺陷|无风险|可以上线|准许发布)"),
]
SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    re.compile(r"(?i)(token|cookie|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}"),
]


def render_qa_report_skeleton(state: QAWorkflowState) -> str:
    source_lines = _render_source_files(state)
    metadata = _path_content(state, "metadata.yml")
    requirement = _path_content(state, "input/requirement.md")
    title = _metadata_value(metadata, "title") or _first_heading(requirement) or "未命名需求"
    prd_prefix = _prd_prefix(state)
    artifact_rows = _artifact_rows(state, prd_prefix)
    review_rows = _review_rows(state)
    scope_summary = _scope_summary(state)
    risks = _risk_rows(state)
    pending_items = _pending_items(state)
    return f"""---
status: needs_human_review
artifact_type: qa_report
human_review_required: true
generated_by: agentic-qa-runtime
---

# QA 报告草稿

> 当前报告为待人工确认草稿；未读取到真实执行结果时，不给出通过率、上线结论或缺陷关闭结论。

## 1. 基本信息

| 项目 | 内容 |
|---|---|
| 需求 | {title} |
| PRD 工作区 | `{prd_prefix}` |
| 报告状态 | needs_human_review |
| 报告来源 | 已有 PRD 输入、正式产物、review 记录和本次 Runtime 上下文 |
| 执行结果口径 | 未读取到结构化测试执行结果，执行数据均标记为待确认 |

## 2. 产物索引

| 产物 | 路径 | 当前可用性 | 说明 |
|---|---|---|---|
{artifact_rows}

### Review Gate 状态

| Review | 状态 | run_id | 待处理 |
|---|---|---|---|
{review_rows}

## 3. 测试范围

- 已纳入报告的范围：{scope_summary}
- 已有测试设计：基于正式测试用例、接口测试草稿、UI 自动化草稿和接口发现报告汇总。
- 需人工确认：本报告是否覆盖当前 PRD 的所有变更范围、角色、环境和依赖系统。

## 4. 执行概况

| 指标 | 当前值 | 来源 | 待确认 |
|---|---|---|---|
| 计划用例数 | 待确认 | `artifacts/testcases.md` 或测试管理平台 | 是否已同步到执行平台 |
| 已执行数 | 待确认 | 执行报告缺失或未结构化 | 是否已有 pytest / Playwright / 手工执行结果 |
| 通过数 | 待确认 | 执行报告缺失或未结构化 | 不得由草稿推断 |
| 失败数 | 待确认 | 执行报告缺失或未结构化 | 失败是否已进入失败分析 |
| 跳过/阻塞数 | 待确认 | 执行报告缺失或未结构化 | 阻塞原因和责任方 |
| 通过率 | 待确认 | 未读取到真实执行结果 | 禁止编造通过率 |

## 5. 缺陷和风险

| 风险/问题 | 影响 | 建议动作 |
|---|---|---|
{risks}

## 6. 未覆盖范围

- 未覆盖或待补充真实执行结果、执行环境、浏览器/设备矩阵、测试账号和测试数据回滚策略。
- 未覆盖未经确认的接口契约差异、错误码字典、权限矩阵、风控和幂等规则。
- 未覆盖图片/原型图中未写入正文的信息；如需求依赖图片内容，需先补充到 `input/requirement.md`。
- 不默认覆盖生产环境、真实用户数据、真实资金/库存/奖励等不可回滚场景。

## 7. 结论草稿

- 当前结论：待人工确认。
- 发布建议：由于未读取到完整执行结果，本报告不能给出正式上线或发布通过结论。
- 后续条件：补齐执行报告、失败分析、缺陷状态和关键风险确认后，再由人工确认最终 QA 结论。

## 8. 待人工确认项

{pending_items}

## 来源文件

{source_lines}
"""


def qa_report_generation_node(state: QAWorkflowState) -> QAWorkflowState:
    if state.task_type != TASK_QA_REPORT:
        return state
    if state.errors:
        return state

    prompt = build_report_prompt(
        state.loaded_files,
        prd_prefix=_prd_prefix(state),
        rag_context=_build_rag_context(state),
        max_input_chars=int(state.llm.get("max_input_chars") or 32000),
    )
    state.warnings.extend(prompt.warnings)
    artifact = _generate_with_optional_llm(
        state,
        prompt=prompt.prompt,
        fallback=render_qa_report_skeleton(state),
    )
    state.draft_artifacts["qa_report"] = artifact
    state.draft_artifact = artifact
    output_path = state.output_paths.get("qa_report")
    if output_path:
        state.output_path = output_path
        _upsert_artifact(
            state,
            name="qa_report",
            artifact_type="qa_report",
            output_path=output_path,
        )
    return state


def qa_report_quality_check_node(state: QAWorkflowState, repo_root: Path) -> QAWorkflowState:
    if state.task_type != TASK_QA_REPORT:
        return state
    if state.errors:
        return state

    artifact = state.draft_artifacts.get("qa_report") or ""
    if not artifact.strip():
        state.quality_errors.append("QA 报告草稿为空。")
        return state
    for section in REQUIRED_QA_REPORT_SECTIONS:
        if not _has_section(artifact, section):
            state.quality_errors.append(f"QA 报告草稿缺少章节: {section}")
    if "待人工确认" not in artifact:
        state.quality_errors.append("QA 报告草稿必须包含待人工确认项。")
    if any(pattern.search(artifact) for pattern in EXECUTION_RESULT_PATTERNS):
        state.quality_errors.append("QA 报告草稿不得伪造执行通过率、零缺陷或发布结论。")
    if any(pattern.search(artifact) for pattern in SECRET_PATTERNS):
        state.quality_errors.append("QA 报告草稿疑似包含真实 token、Cookie 或密钥。")
    _check_output_path(state, repo_root)
    return state


def _metadata_value(metadata: str, key: str) -> str | None:
    for line in metadata.splitlines():
        if line.startswith(f"{key}:"):
            value = line.split(":", 1)[1].strip().strip("'\"")
            return value or None
    return None


def _first_heading(markdown: str) -> str | None:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line.lstrip("#").strip()
    return None


def _artifact_rows(state: QAWorkflowState, prd_prefix: str) -> str:
    artifacts = [
        ("需求分析", "artifacts/requirement-analysis.md"),
        ("测试用例", "artifacts/testcases.md"),
        ("接口测试草稿", "artifacts/api-test-draft.md"),
        ("UI 自动化草稿", "artifacts/ui-test-draft.md"),
        ("接口发现报告", "artifacts/api-discovery-report.md"),
        ("测试执行报告", "artifacts/execution-report.md"),
        ("失败分析", "artifacts/failure-analysis.md"),
        ("Bug 草稿", "artifacts/bug-draft.md"),
    ]
    rows = []
    for name, relative in artifacts:
        path = f"{prd_prefix}/{relative}"
        exists = path in state.loaded_files
        status = "已读取" if exists else "未读取/待补充"
        note = "可作为报告依据" if exists else "本报告仅记录缺口，不推断结论"
        rows.append(f"| {name} | `{relative}` | {status} | {note} |")
    return "\n".join(rows)


def _review_rows(state: QAWorkflowState) -> str:
    rows = []
    for path, content in sorted(state.loaded_files.items()):
        if not path.endswith(".review.yml"):
            continue
        status = _metadata_value(content, "status") or "待确认"
        run_id = _metadata_value(content, "run_id") or "待确认"
        next_action = _metadata_value(content, "next_action") or "待确认"
        rows.append(f"| `{path}` | {status} | {run_id} | {next_action} |")
    if not rows:
        rows.append("| Review 记录 | 待确认 | 待确认 | 需补充 review 记录 |")
    return "\n".join(rows)


def _scope_summary(state: QAWorkflowState) -> str:
    requirement = _path_content(state, "input/requirement.md")
    bullets = [
        line.strip()[2:].strip()
        for line in requirement.splitlines()
        if line.strip().startswith(("- ", "* "))
    ]
    if bullets:
        return "；".join(bullets[:4])
    heading = _first_heading(requirement)
    return heading or "PRD 正文描述的业务范围，具体边界需人工确认"


def _risk_rows(state: QAWorkflowState) -> str:
    risks = [
        "| 执行结果缺失 | 无法判断真实通过率和失败分布 | 补充执行报告或测试平台结果 |",
        (
            "| 接口契约待核对 | API 测试草稿或接口发现报告可能只代表候选接口 | "
            "与 Swagger / Apifox 核对字段、错误码、权限、风控和幂等 |"
        ),
        (
            "| Review 状态未完全确认 | 未确认产物不能作为正式 QA 结论 | "
            "完成 Review Gate 并 promote 正式产物 |"
        ),
    ]
    if "artifacts/failure-analysis.md" not in "\n".join(state.loaded_files):
        risks.append(
            "| 失败分析缺失 | 失败原因可能无法区分产品、环境、数据或脚本问题 | "
            "补齐失败分析后再形成最终结论 |"
        )
    return "\n".join(risks)


def _pending_items(state: QAWorkflowState) -> str:
    items = [
        "是否已有真实执行结果、执行环境和测试数据版本。",
        "是否存在未关闭 P0/P1 缺陷、阻塞问题或需业务接受的风险。",
        "接口字段必填、错误码、权限、风控、幂等和审计口径是否已与接口契约核对。",
        "本报告是否允许作为正式 QA 报告候选进入 Review Gate。",
    ]
    if state.prototype_notes.get("requirement_has_images"):
        items.append("需求图片/原型图中的信息是否已补充到正文并纳入测试范围。")
    return "\n".join(f"- [ ] {item}" for item in items)


def _has_section(markdown: str, section: str) -> bool:
    return bool(re.search(rf"^##\s+\d+\.\s+{re.escape(section)}\s*$", markdown, re.MULTILINE))


def _check_output_path(state: QAWorkflowState, repo_root: Path) -> None:
    output_path = state.output_paths.get("qa_report")
    if not output_path:
        state.quality_errors.append("缺少 QA 报告输出路径。")
        return
    prd_path = resolve_prd_path(repo_root, state.prd_path)
    if not (repo_root / Path(output_path)).resolve().is_relative_to(prd_path.resolve()):
        state.quality_errors.append("QA 报告输出路径必须位于目标 PRD 工作区内。")
    if not is_run_candidate_markdown_path(
        output_path, run_id=state.run_id, artifact_key="qa_report"
    ):
        state.quality_errors.append("QA 报告输出路径不符合约定: runs/<run_id>/qa-report.preview.md")
