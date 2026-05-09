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
    "approved",
    "needs_changes",
    "rejected",
    "needs_human_confirmation",
    "confirmed",
    "archived",
}
BLOCKING_STATUSES = {"needs_human_review", "needs_human_confirmation"}
WORKSPACE_DIRS = [
    "10-analysis",
    "20-testcases",
    "30-api-tests/generated",
    "40-ui-tests/generated",
    "50-execution-results",
    "60-failure-analysis",
    "70-bugs",
    "80-reports",
    "90-archive",
]
REQUIRED_FILES = ["requirement.md", "api-doc.md", "metadata.yml"]
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
            "requirement": f"{workspace}/requirement.md",
            "api_doc": f"{workspace}/api-doc.md",
            "analysis": f"{workspace}/10-analysis/requirement-analysis.md",
            "testcases": f"{workspace}/20-testcases/testcases.md",
            "api_test_plan": f"{workspace}/30-api-tests/api-test-plan.md",
            "api_tests": f"{workspace}/30-api-tests/generated/",
            "ui_tests": f"{workspace}/40-ui-tests/generated/",
            "execution_results": f"{workspace}/50-execution-results/",
            "execution_report": f"{workspace}/50-execution-results/execution-report.md",
            "failure_analysis": f"{workspace}/60-failure-analysis/failure-analysis.md",
            "bugs": f"{workspace}/70-bugs/",
            "report_draft": f"{workspace}/80-reports/qa-report-draft.md",
            "report": f"{workspace}/80-reports/qa-report.md",
            "archive": f"{workspace}/90-archive/",
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
                "name": "执行结果确认",
                "status": "needs_human_confirmation",
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
    created_by: str = "Codex",
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
        "requirement.md": requirement_placeholder(resolved_title),
        "api-doc.md": api_doc_placeholder(resolved_title),
    }
    for relative_path, content in files.items():
        target = workspace / relative_path
        if not target.exists():
            target.write_text(content, encoding="utf-8")

    metadata_path = workspace / "metadata.yml"
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

    metadata_path = workspace / "metadata.yml"
    if metadata_path.exists():
        try:
            metadata = read_yaml(metadata_path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"metadata.yml 无法解析: {exc}")
        else:
            for key in REQUIRED_METADATA_KEYS:
                if key not in metadata:
                    errors.append(f"metadata.yml 缺少字段: {key}")
            status = metadata.get("status")
            if status not in ALLOWED_STATUSES:
                errors.append(f"metadata.yml status 非法: {status}")
            review_gates = metadata.get("review_gates")
            if not isinstance(review_gates, list) or not review_gates:
                errors.append("metadata.yml review_gates 必须是非空列表")
            else:
                for index, gate in enumerate(review_gates, start=1):
                    if not isinstance(gate, dict):
                        errors.append(f"review_gates[{index}] 必须是对象")
                        continue
                    gate_status = gate.get("status")
                    if gate_status not in ALLOWED_STATUSES:
                        errors.append(f"review_gates[{index}] status 非法: {gate_status}")
            if not isinstance(metadata.get("artifacts"), dict):
                errors.append("metadata.yml artifacts 必须是对象")

    return ValidationResult(workspace=workspace, errors=errors)


def first_existing_text(paths: list[Path], max_chars: int = 1200) -> str:
    for path in paths:
        if path.is_file():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return content[:max_chars]
    return "未找到可用内容。"


def generate_markdown_report(workspace_path: Path | str) -> Path:
    workspace = Path(workspace_path)
    result = validate_workspace(workspace)
    if not result.ok:
        raise RuntimeError("PRD 工作区校验失败: " + "; ".join(result.errors))

    metadata = read_yaml(workspace / "metadata.yml")
    report_dir = workspace / "80-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "qa-report-draft.md"

    requirement_summary = first_existing_text(
        [workspace / "10-analysis/requirement-analysis.md", workspace / "requirement.md"]
    )
    testcase_summary = first_existing_text([workspace / "20-testcases/testcases.md"])
    execution_summary = first_existing_text(
        [
            workspace / "50-execution-results/execution-report.md",
            workspace / "50-execution-results/test-results-summary.md",
            workspace / "50-execution-results/pytest-report.json",
        ]
    )
    failure_summary = first_existing_text([workspace / "60-failure-analysis/failure-analysis.md"])

    report = f"""---
status: needs_human_confirmation
human_confirmation_required: true
artifact_type: qa_report_draft
generated_by: scripts/generate_markdown_report.py
---

# QA 报告草稿：{metadata.get("title")}

## 基本信息

- 需求 ID：{metadata.get("requirement_id")}
- 当前状态：{metadata.get("status")}
- 负责人：{metadata.get("owner")}
- 报告生成时间：{now_iso()}
- 正式报告路径：{workspace.as_posix()}/80-reports/qa-report.md
- 当前报告不得作为正式发布结论。

## 需求与分析摘要

{requirement_summary}

## 测试用例摘要

{testcase_summary}

## 执行结果摘要

{execution_summary}

## 失败分析摘要

{failure_summary}

## 结论草稿

- 当前报告由脚本生成，结论必须经过人工确认。
- 若存在未审核或未确认状态，不允许归档。

## 待人工确认

- 需求理解是否准确。
- 用例覆盖是否充分。
- 自动化结果是否可信。
- 缺陷判断和发布建议是否可接受。
"""
    report_path.write_text(report, encoding="utf-8")
    return report_path


def collect_test_results(workspace_path: Path | str) -> Path:
    workspace = Path(workspace_path)
    result_dir = workspace / "50-execution-results"
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

    metadata_path = workspace / "metadata.yml"
    metadata = read_yaml(metadata_path)
    blocked = find_blocking_statuses(metadata)
    if blocked:
        raise RuntimeError("存在未审核或未确认状态，拒绝归档: " + "; ".join(blocked))

    archive_dir = workspace / "90-archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / "archive-index.md"
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
`needs_human_review` 或 `needs_human_confirmation` 状态。
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
