"""File-based PRD workspace utilities for Agentic-QA scripts."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ALLOWED_STATUSES = {
    "draft",
    "needs_human_review",
    "reviewed",
    "needs_revision",
    "approved",
    # Legacy-compatible statuses kept for existing workspaces.
    "needs_changes",
    "rejected",
    "needs_human_confirmation",
    "confirmed",
    "archived",
}
BLOCKING_STATUSES = {
    "needs_human_review",
    "needs_revision",
    "needs_changes",
    "needs_human_confirmation",
}
WORKSPACE_DIRS = [
    "input",
    "input/attachments",
    "context",
    "analysis",
    "cases",
    "automation/api/generated",
    "automation/ui/generated",
    "execution/runs",
    "defects",
    "defects/bug-drafts",
    "report",
    "review",
    "exports",
    "archive",
]
REQUIRED_FILES = ["input/requirement.md", "input/api.md", "workspace.yml"]
REQUIRED_METADATA_KEYS = [
    "requirement_id",
    "title",
    "status",
    "owner",
    "created_by",
    "last_updated_by",
    "artifacts",
    "review_gates",
]
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


@dataclass(frozen=True)
class ValidationResult:
    """Validation outcome for a PRD workspace."""

    workspace: Path
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def validate_slug(slug: str) -> None:
    if not SLUG_RE.match(slug):
        raise ValueError("需求目录名必须使用小写字母、数字和连字符，例如 demo-requirement")


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} 必须是 YAML 对象")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def default_metadata(slug: str, title: str, owner: str, created_by: str) -> dict[str, Any]:
    workspace = f"prd/{slug}"
    return {
        "requirement_id": slug,
        "title": title,
        "status": "draft",
        "owner": owner,
        "created_by": created_by,
        "last_updated_by": created_by,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "artifacts": {
            "requirement": f"{workspace}/input/requirement.md",
            "api_doc": f"{workspace}/input/api.md",
            "analysis": f"{workspace}/analysis/requirement-analysis.md",
            "testcases": f"{workspace}/cases/test-cases.md",
            "api_test_plan": f"{workspace}/automation/api/test-plan.md",
            "api_tests": f"{workspace}/automation/api/generated/",
            "ui_tests": f"{workspace}/automation/ui/generated/",
            "execution_results": f"{workspace}/execution/runs/",
            "execution_report": f"{workspace}/execution/runs/latest/summary.md",
            "failure_analysis": f"{workspace}/defects/failure-analysis.md",
            "bugs": f"{workspace}/defects/bug-drafts/",
            "report_draft": f"{workspace}/report/qa-review.md",
            "report": f"{workspace}/report/qa-report.md",
            "archive": f"{workspace}/archive/",
        },
        "review_gates": [
            {
                "name": "需求分析审核",
                "status": "needs_human_review",
                "owner": "产品负责人",
                "required_before": "生成测试用例",
            },
            {
                "name": "测试用例审核",
                "status": "needs_human_review",
                "owner": "QA 负责人",
                "required_before": "生成自动化脚本",
            },
            {
                "name": "执行结果审核",
                "status": "needs_human_review",
                "owner": "QA 负责人",
                "required_before": "归档",
            },
        ],
    }


def requirement_placeholder(title: str) -> str:
    return f"""# {title}

## 背景

请在此补充业务背景、目标用户、入口和依赖系统。

## 需求范围

- 待补充核心业务流程。
- 待补充异常场景和边界条件。
- 待补充权限、风控、审计或合规要求。

## 验收标准

- 需求描述已被产品负责人审核。
- 关键规则有明确输入、处理逻辑和输出。
- 影响范围、非目标范围和风险已记录。

## 待人工审核

- 需求是否完整。
- 业务规则是否可测试。
- 是否允许 AI 基于本文生成测试产物。
"""


def api_doc_placeholder(title: str) -> str:
    return f"""# {title} API 文档草稿

## 接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/example | 示例接口，创建工作区后请替换为真实接口 |

## 通用约定

- 请求和响应使用 JSON。
- 认证方式、错误码、幂等要求需要人工补充。
- 自动化脚本只能依据已审核接口文档生成。
"""


def create_workspace(
    slug: str,
    prd_root: Path | str = "prd",
    title: str | None = None,
    owner: str = "待指定",
    created_by: str = "Agentic-QA",
) -> Path:
    """Create a standard PRD workspace without overwriting existing files."""

    validate_slug(slug)
    root = Path(prd_root)
    workspace = root / slug
    workspace.mkdir(parents=True, exist_ok=True)

    for directory in WORKSPACE_DIRS:
        directory_path = workspace / directory
        directory_path.mkdir(parents=True, exist_ok=True)
        gitkeep = directory_path / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")

    resolved_title = title or slug.replace("-", " ").title()
    files = {
        "input/requirement.md": requirement_placeholder(resolved_title),
        "input/api.md": api_doc_placeholder(resolved_title),
    }
    for relative_path, content in files.items():
        target = workspace / relative_path
        if not target.exists():
            target.write_text(content, encoding="utf-8")

    metadata_path = workspace / "workspace.yml"
    if not metadata_path.exists():
        metadata = default_metadata(slug, resolved_title, owner, created_by)
        write_yaml(metadata_path, metadata)

    update_registry(root, slug, resolved_title, workspace)
    return workspace


def update_registry(prd_root: Path, slug: str, title: str, workspace: Path) -> None:
    prd_root.mkdir(parents=True, exist_ok=True)
    registry_path = prd_root / "_registry.yml"
    if registry_path.exists():
        registry = read_yaml(registry_path)
    else:
        registry = {"requirements": []}

    requirements = registry.setdefault("requirements", [])
    if not isinstance(requirements, list):
        raise ValueError("prd/_registry.yml 中 requirements 必须是列表")

    already_registered = any(
        item.get("requirement_id") == slug for item in requirements if isinstance(item, dict)
    )
    if not already_registered:
        requirements.append(
            {
                "requirement_id": slug,
                "title": title,
                "path": workspace.as_posix(),
                "status": "draft",
            }
        )
    write_yaml(registry_path, registry)


def validate_workspace(workspace_path: Path | str) -> ValidationResult:
    workspace = Path(workspace_path)
    errors: list[str] = []

    if not workspace.exists():
        return ValidationResult(workspace=workspace, errors=[f"工作区不存在: {workspace}"])

    for directory in WORKSPACE_DIRS:
        if not (workspace / directory).is_dir():
            errors.append(f"缺少目录: {directory}")

    for filename in REQUIRED_FILES:
        if not (workspace / filename).is_file():
            errors.append(f"缺少文件: {filename}")

    metadata_path = workspace / "workspace.yml"
    if metadata_path.exists():
        try:
            metadata = read_yaml(metadata_path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"workspace.yml 无法解析: {exc}")
        else:
            for key in REQUIRED_METADATA_KEYS:
                if key not in metadata:
                    errors.append(f"workspace.yml 缺少字段: {key}")
            status = metadata.get("status")
            if status not in ALLOWED_STATUSES:
                errors.append(f"workspace.yml status 非法: {status}")
            review_gates = metadata.get("review_gates")
            if not isinstance(review_gates, list) or not review_gates:
                errors.append("workspace.yml review_gates 必须是非空列表")
            else:
                for index, gate in enumerate(review_gates, start=1):
                    if not isinstance(gate, dict):
                        errors.append(f"review_gates[{index}] 必须是对象")
                        continue
                    gate_status = gate.get("status")
                    if gate_status not in ALLOWED_STATUSES:
                        errors.append(f"review_gates[{index}] status 非法: {gate_status}")
            if not isinstance(metadata.get("artifacts"), dict):
                errors.append("workspace.yml artifacts 必须是对象")

    return ValidationResult(workspace=workspace, errors=errors)


ARTIFACT_RELATIVE_PATHS = {
    "requirement": "input/requirement.md",
    "api_doc": "input/api.md",
    "analysis": "analysis/requirement-analysis.md",
    "testcases": "cases/test-cases.md",
    "api_test_plan": "automation/api/test-plan.md",
    "api_tests": "automation/api/generated",
    "ui_tests": "automation/ui/generated",
    "execution_results": "execution/runs",
    "execution_report": "execution/runs/latest/summary.md",
    "failure_analysis": "defects/failure-analysis.md",
    "bugs": "defects/bug-drafts",
    "report_draft": "report/qa-review.md",
    "report": "report/qa-report.md",
    "archive": "archive",
}


def read_text_if_exists(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def strip_front_matter(content: str) -> str:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return content.strip()

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :]).strip()
    return content.strip()


def section_text(content: str, heading: str) -> str:
    lines = strip_front_matter(content).splitlines()
    collected: list[str] = []
    in_section = False
    section_level = 0

    for line in lines:
        match = re.match(r"^(#{2,6})\s+(.+?)\s*$", line)
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            if in_section and level <= section_level:
                break
            if title == heading:
                in_section = True
                section_level = level
                continue
        if in_section:
            collected.append(line)

    return "\n".join(collected).strip()


def is_table_separator(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def parse_markdown_table(content: str) -> tuple[list[str], list[list[str]]]:
    headers: list[str] = []
    rows: list[list[str]] = []
    in_table = False

    for line in strip_front_matter(content).splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            if in_table and headers:
                break
            continue

        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if is_table_separator(cells):
            in_table = True
            continue
        if not headers:
            headers = cells
            in_table = True
            continue
        rows.append(cells)

    return headers, rows


def compact_markdown_items(content: str, max_items: int = 5) -> list[str]:
    items: list[str] = []
    for line in strip_front_matter(content).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("|"):
            continue
        if stripped in {"---"} or re.fullmatch(r"[-*]+", stripped):
            continue
        stripped = re.sub(r"^- \[[ xX]\]\s*", "- ", stripped)
        stripped = re.sub(r"\s+", " ", stripped)
        if stripped not in items:
            items.append(stripped)
        if len(items) >= max_items:
            break
    return items


def document_intro_items(content: str, max_items: int = 3) -> list[str]:
    items: list[str] = []
    for line in strip_front_matter(content).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            break
        if stripped.startswith("#") or stripped.startswith("|"):
            continue
        stripped = re.sub(r"\s+", " ", stripped)
        items.append(stripped)
        if len(items) >= max_items:
            break
    return items


def bullet_lines(items: list[str], empty_text: str = "未发现可摘要内容。") -> str:
    if not items:
        return f"- {empty_text}"
    return "\n".join(f"- {item.lstrip('- ').strip()}" for item in items)


def artifact_exists(workspace: Path, name: str, path_text: str) -> bool:
    relative = ARTIFACT_RELATIVE_PATHS.get(name)
    candidates = []
    if relative:
        candidates.append(workspace / relative)

    path = Path(path_text)
    candidates.append(path if path.is_absolute() else Path.cwd() / path)
    return any(candidate.exists() for candidate in candidates)


def artifact_index(metadata: dict[str, Any], workspace: Path) -> str:
    artifacts = metadata.get("artifacts", {})
    if not isinstance(artifacts, dict) or not artifacts:
        return "- workspace.yml 未记录 artifacts。"

    lines = ["| 产物 | 路径 | 当前状态 |", "|---|---|---|"]
    for name, path_text in artifacts.items():
        if not isinstance(path_text, str):
            continue
        exists = artifact_exists(workspace, name, path_text)
        status = "存在" if exists else "待生成"
        if name == "report_draft" and not exists:
            status = "本次生成"
        lines.append(f"| {name} | `{path_text}` | {status} |")
    return "\n".join(lines)


def summarize_requirement_analysis(workspace: Path) -> str:
    analysis = read_text_if_exists(workspace / "analysis/requirement-analysis.md")
    requirement = read_text_if_exists(workspace / "input/requirement.md")
    source = analysis or requirement
    if not source:
        return "- 未找到需求分析或需求原文。"

    summary = section_text(source, "需求摘要") or section_text(source, "需求范围")
    items = compact_markdown_items(summary, max_items=4)

    business_rules = section_text(source, "业务规则")
    _, rule_rows = parse_markdown_table(business_rules)
    if rule_rows:
        items.append(f"已识别业务规则 {len(rule_rows)} 条。")

    risk_items = compact_markdown_items(section_text(source, "测试风险"), max_items=3)
    items.extend(f"风险：{item.lstrip('- ').strip()}" for item in risk_items)
    return bullet_lines(items)


def summarize_testcases(workspace: Path) -> str:
    content = read_text_if_exists(workspace / "cases/test-cases.md")
    if not content:
        return "- 未找到测试用例草稿。"

    headers, rows = parse_markdown_table(content)
    if not rows:
        return "- 未解析到测试用例表，需人工检查 `cases/test-cases.md`。"

    priority_counts: dict[str, int] = {}
    title_index = headers.index("标题") if "标题" in headers else 0
    priority_index = headers.index("优先级") if "优先级" in headers else None
    titles = []

    for row in rows:
        if title_index < len(row):
            titles.append(row[title_index])
        if priority_index is not None and priority_index < len(row):
            priority = row[priority_index] or "未标记"
            priority_counts[priority] = priority_counts.get(priority, 0) + 1

    priority_summary = "、".join(
        f"{priority} {count} 条" for priority, count in sorted(priority_counts.items())
    )
    lines = [
        f"- 已识别测试用例 {len(rows)} 条。",
        f"- 优先级分布：{priority_summary or '未标记'}。",
    ]
    if titles:
        lines.append("- 代表性用例：" + "；".join(titles[:5]) + "。")
    lines.append("- 完整用例请查看 `cases/test-cases.md`。")
    return "\n".join(lines)


def summarize_execution(workspace: Path) -> str:
    content = read_text_if_exists(workspace / "execution/runs/latest/summary.md")
    if not content:
        return "- 未找到执行报告，当前不提供真实执行结论。"

    command_section = section_text(content, "已执行的本地命令")
    _, rows = parse_markdown_table(command_section)
    passed = sum(1 for row in rows if any(cell == "通过" for cell in row))
    lines = [
        f"- 已记录本地验收命令 {len(rows)} 条，通过 {passed} 条。",
        "- 真实业务接口测试是否执行需以授权环境和执行报告为准。",
    ]

    skipped = compact_markdown_items(section_text(content, "未执行的真实业务接口测试"), max_items=2)
    lines.extend(f"- 未执行说明：{item.lstrip('- ').strip()}" for item in skipped)
    return "\n".join(lines)


def summarize_failure_analysis(workspace: Path) -> str:
    content = read_text_if_exists(workspace / "defects/failure-analysis.md")
    if not content:
        return "- 未找到失败分析草稿。"

    framework = section_text(content, "失败分类框架")
    _, rows = parse_markdown_table(framework)
    items = [f"已记录失败分类示例 {len(rows)} 条。"] if rows else []
    intro = document_intro_items(content, max_items=2)
    items.extend(intro)
    items.append("真实缺陷结论必须等待人工确认和真实失败证据。")
    return bullet_lines(items)


def collect_human_confirmation_items(metadata: dict[str, Any], workspace: Path) -> str:
    items: list[str] = []
    review_gates = metadata.get("review_gates", [])
    if isinstance(review_gates, list):
        for gate in review_gates:
            if not isinstance(gate, dict):
                continue
            status = gate.get("status")
            if status in BLOCKING_STATUSES:
                name = gate.get("name", "未命名审核门")
                owner = gate.get("owner", "待指定")
                items.append(f"{name}：{status}，负责人 {owner}。")

    paths = [
        workspace / "analysis/requirement-analysis.md",
        workspace / "cases/test-cases.md",
        workspace / "automation/api/test-plan.md",
        workspace / "execution/runs/latest/summary.md",
        workspace / "defects/failure-analysis.md",
    ]
    for path in paths:
        content = read_text_if_exists(path)
        if not content:
            continue
        relative = path.relative_to(workspace).as_posix()
        for heading in ("待人工确认", "待人工审核"):
            for item in compact_markdown_items(section_text(content, heading), max_items=4):
                items.append(f"{relative}：{item.lstrip('- ').strip()}")

    deduped = list(dict.fromkeys(items))[:11]
    deduped.append("正式 `qa-report.md` 只能在人工确认后生成。")
    return bullet_lines(deduped)


def generate_markdown_report(workspace_path: Path | str) -> Path:
    workspace = Path(workspace_path)
    result = validate_workspace(workspace)
    if not result.ok:
        raise RuntimeError("PRD 工作区校验失败: " + "; ".join(result.errors))

    metadata = read_yaml(workspace / "workspace.yml")
    report_dir = workspace / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "qa-review.md"

    artifacts = artifact_index(metadata, workspace)
    requirement_summary = summarize_requirement_analysis(workspace)
    testcase_summary = summarize_testcases(workspace)
    execution_summary = summarize_execution(workspace)
    failure_summary = summarize_failure_analysis(workspace)
    confirmation_items = collect_human_confirmation_items(metadata, workspace)

    report = f"""---
status: needs_human_review
human_review_required: true
artifact_type: qa_report_draft
generated_by: scripts/generate_markdown_report.py
---

# QA 报告草稿：{metadata.get("title")}

## 基本信息

- 需求 ID：{metadata.get("requirement_id")}
- 当前状态：{metadata.get("status")}
- 负责人：{metadata.get("owner")}
- 报告生成时间：{now_iso()}
- 正式报告路径：{workspace.as_posix()}/report/qa-report.md
- 当前报告不得作为正式发布结论。

## 产物索引

{artifacts}

## 需求分析摘要

{requirement_summary}

## 测试用例摘要

{testcase_summary}

## 自动化与执行摘要

{execution_summary}

## 失败分析摘要

{failure_summary}

## 风险与阻塞项

- metadata 中仍存在待审核或待确认状态时，不允许归档。
- 未提供授权非生产环境前，不应把示例 API 脚本结果作为真实业务测试结论。
- 当前报告只提供摘要和产物索引，完整证据需通过上方路径人工查看。

## 待人工确认项

{confirmation_items}

## 结论草稿

- 当前报告由脚本生成，结论必须经过人工确认。
- 若存在未审核或未确认状态，不允许归档。
- 当前报告不得作为正式发布结论。
"""
    report_path.write_text(report, encoding="utf-8")
    return report_path


def collect_test_results(workspace_path: Path | str) -> Path:
    workspace = Path(workspace_path)
    result_dir = workspace / "execution/runs"
    result_dir.mkdir(parents=True, exist_ok=True)
    summary_path = result_dir / "test-results-summary.md"
    files = sorted(
        path for path in result_dir.rglob("*") if path.is_file() and path != summary_path
    )

    lines = ["# 测试结果汇总", ""]
    if not files:
        lines.append("未发现测试结果文件。")
    else:
        lines.append("| 文件 | 大小 | 说明 |")
        lines.append("|---|---:|---|")
        for path in files:
            relative = path.relative_to(workspace).as_posix()
            lines.append(f"| {relative} | {path.stat().st_size} | 待人工解读 |")

    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path


def find_blocking_statuses(value: Any, prefix: str = "metadata") -> list[str]:
    blocked: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            blocked.extend(find_blocking_statuses(item, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            blocked.extend(find_blocking_statuses(item, f"{prefix}[{index}]"))
    elif isinstance(value, str) and value in BLOCKING_STATUSES:
        blocked.append(f"{prefix}={value}")
    return blocked


def archive_requirement(workspace_path: Path | str) -> Path:
    workspace = Path(workspace_path)
    result = validate_workspace(workspace)
    if not result.ok:
        raise RuntimeError("PRD 工作区校验失败: " + "; ".join(result.errors))

    metadata_path = workspace / "workspace.yml"
    metadata = read_yaml(metadata_path)
    blocked = find_blocking_statuses(metadata)
    if blocked:
        raise RuntimeError("存在未审核或未确认状态，拒绝归档: " + "; ".join(blocked))

    archive_dir = workspace / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / "index.md"
    artifacts = metadata.get("artifacts", {})
    artifact_lines = []
    if isinstance(artifacts, dict):
        artifact_lines = [f"- {name}: {path}" for name, path in artifacts.items()]

    archive = f"""# 归档索引：{metadata.get("title")}

- 需求 ID：{metadata.get("requirement_id")}
- 归档时间：{now_iso()}
- 归档前状态：{metadata.get("status")}

## 产物清单

{chr(10).join(artifact_lines) if artifact_lines else "- 未记录产物。"}

## 归档说明

本索引由 `scripts/archive_requirement.py` 生成。归档前已检查 metadata 中不存在
`needs_human_review`、`needs_revision`、`needs_changes` 或 `needs_human_confirmation` 状态。
"""
    archive_path.write_text(archive, encoding="utf-8")
    metadata["status"] = "archived"
    metadata["last_updated_by"] = "archive_requirement.py"
    metadata["updated_at"] = now_iso()
    write_yaml(metadata_path, metadata)
    return archive_path


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="创建标准 PRD 需求工作区")
    parser.add_argument("slug", help="需求目录名，例如 demo-requirement")
    parser.add_argument("--prd-root", default="prd", help="PRD 根目录")
    parser.add_argument("--title", default=None, help="需求标题")
    parser.add_argument("--owner", default="待指定", help="需求负责人")
    args = parser.parse_args()

    workspace = create_workspace(
        slug=args.slug,
        prd_root=Path(args.prd_root),
        title=args.title,
        owner=args.owner,
        created_by="scripts/create_prd_workspace.py",
    )
    print(f"已创建或更新 PRD 工作区: {workspace.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
