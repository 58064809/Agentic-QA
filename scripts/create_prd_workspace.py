"""Create and validate Agentic-QA PRD workspaces.

This script is intentionally lightweight: it creates the current workspace shape used
by README and docs, without invoking LLMs or production integrations.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from runtime.workspace import (
    ALLOWED_ARTIFACT_STATUSES,
    ARTIFACT_SPECS,
    BLOCKING_ARTIFACT_STATUSES,
    REQUIRED_METADATA_KEYS,
    REQUIRED_WORKSPACE_FILES,
    PRDWorkspace,
    default_metadata,
    history_index,
    now_iso,
    read_yaml_mapping,
    review_record,
    write_yaml_mapping,
)
from runtime.workspace import (
    WORKSPACE_DIRS as STANDARD_WORKSPACE_DIRS,
)

ALLOWED_STATUSES = ALLOWED_ARTIFACT_STATUSES
BLOCKING_STATUSES = BLOCKING_ARTIFACT_STATUSES

WORKSPACE_DIRS = [
    *STANDARD_WORKSPACE_DIRS,
]

REQUIRED_FILES = REQUIRED_WORKSPACE_FILES

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


@dataclass(frozen=True)
class ValidationResult:
    workspace: Path
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_slug(slug: str) -> None:
    if not SLUG_RE.match(slug):
        raise ValueError("需求目录名必须使用小写字母、数字和连字符，例如 demo-requirement")


def read_yaml(path: Path) -> dict[str, Any]:
    return read_yaml_mapping(path)


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    write_yaml_mapping(path, data)


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
"""


def api_doc_placeholder(title: str) -> str:
    return f"""# {title} API 文档草稿

## 接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/example | 示例接口，创建工作区后请替换为真实接口 |

## 通用约定

- 请求和响应使用 JSON。
- 认证方式、错误码、幂等要求需要补充。
"""


def artifact_front_matter(artifact_type: str, status: str = "needs_human_review") -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "status": status,
        "human_review_required": True,
        "source_requirement": "input/requirement.md",
        "source_api": "input/api.md",
        "generated_by": "agentic-qa-runtime",
        "run_id": "",
        "created_at": "",
        "updated_at": "",
    }


def create_workspace(
    slug: str,
    prd_root: Path | str = "prd",
    title: str | None = None,
    created_by: str = "Agentic-QA",
) -> Path:
    """Create a standard PRD workspace without overwriting existing files."""

    validate_slug(slug)
    root = Path(prd_root)
    workspace = root / slug
    model = PRDWorkspace(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    model.ensure_directories()
    for directory in WORKSPACE_DIRS:
        directory_path = workspace / directory
        gitkeep = directory_path / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")

    resolved_title = title or slug.replace("-", " ").title()
    files = {
        "input/requirement.md": requirement_placeholder(resolved_title),
        "input/api.md": api_doc_placeholder(resolved_title),
        "artifacts/history/testcases/index.yml": yaml.safe_dump(
            history_index("artifacts/testcases.md", "testcases"),
            allow_unicode=True,
            sort_keys=False,
        ),
        "artifacts/history/requirement-analysis/index.yml": yaml.safe_dump(
            history_index("artifacts/requirement-analysis.md", "requirement_analysis"),
            allow_unicode=True,
            sort_keys=False,
        ),
        "artifacts/history/qa-report/index.yml": yaml.safe_dump(
            history_index("artifacts/qa-report.md", "qa_report"),
            allow_unicode=True,
            sort_keys=False,
        ),
    }
    for relative_path, content in files.items():
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text(content, encoding="utf-8")

    reviews = {
        spec["review_path"]: review_record(spec["current_path"], spec["artifact_type"])
        for spec in ARTIFACT_SPECS.values()
    }
    for relative_path, data in reviews.items():
        target = workspace / relative_path
        if not target.exists():
            write_yaml(target, data)

    metadata_path = workspace / "metadata.yml"
    if not metadata_path.exists():
        write_yaml(metadata_path, default_metadata(slug, resolved_title, created_by))

    update_registry(root, slug, resolved_title, workspace)
    return workspace


def update_registry(prd_root: Path, slug: str, title: str, workspace: Path) -> None:
    prd_root.mkdir(parents=True, exist_ok=True)
    registry_path = prd_root / "_registry.yml"
    registry = read_yaml(registry_path) if registry_path.exists() else {"requirements": []}
    requirements = registry.setdefault("requirements", [])
    if not isinstance(requirements, list):
        raise ValueError("prd/_registry.yml 中 requirements 必须是列表")
    exists = any(
        item.get("requirement_id") == slug for item in requirements if isinstance(item, dict)
    )
    if not exists:
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
            if not isinstance(metadata.get("artifacts"), dict):
                errors.append("metadata.yml artifacts 必须是对象")
            if not isinstance(metadata.get("reviews"), dict):
                errors.append("metadata.yml reviews 必须是对象")

    for review_file in [
        "reviews/requirement-analysis.review.yml",
        "reviews/testcases.review.yml",
        "reviews/qa-report.review.yml",
    ]:
        path = workspace / review_file
        if path.exists():
            try:
                record = read_yaml(path)
            except (OSError, ValueError, yaml.YAMLError) as exc:
                errors.append(f"{review_file} 无法解析: {exc}")
                continue
            if record.get("status") not in ALLOWED_STATUSES:
                errors.append(f"{review_file} status 非法: {record.get('status')}")

    return ValidationResult(workspace=workspace, errors=errors)


def generate_markdown_report(workspace_path: Path | str) -> Path:
    workspace = Path(workspace_path)
    metadata = read_yaml(workspace / "metadata.yml")
    target = workspace / "artifacts/qa-report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    content = f"""---
artifact_type: qa_report
status: needs_human_review
human_review_required: true
source_requirement: input/requirement.md
generated_by: agentic-qa-runtime
---

# QA 报告草稿：{metadata.get('title', workspace.name)}

## 产物索引

| 产物 | 路径 | 当前状态 |
|---|---|---|
| 需求分析 | `artifacts/requirement-analysis.md` | 待生成 |
| 测试用例 | `artifacts/testcases.md` | 待生成 |
| QA 报告 | `artifacts/qa-report.md` | 本次生成 |

## 待人工确认项

- [ ] 需求范围是否完整。
- [ ] 测试用例是否覆盖核心链路、异常和边界。
- [ ] 是否允许将本报告作为正式 QA 产物。
"""
    target.write_text(content, encoding="utf-8")
    return target


def archive_requirement(workspace_path: Path | str) -> Path:
    workspace = Path(workspace_path)
    result = validate_workspace(workspace)
    if not result.ok:
        raise RuntimeError("拒绝归档：" + "; ".join(result.errors))
    blocking: list[str] = []
    for review_file in workspace.glob("reviews/*.review.yml"):
        record = read_yaml(review_file)
        status = record.get("status")
        if status in BLOCKING_STATUSES:
            blocking.append(f"{review_file.name}:{status}")
    if blocking:
        raise RuntimeError("拒绝归档：存在未完成确认 " + ", ".join(blocking))
    archive_index = workspace / "artifacts/archive-index.md"
    archive_index.write_text("# 归档索引\n\n当前需求已满足归档条件。\n", encoding="utf-8")
    metadata = read_yaml(workspace / "metadata.yml")
    metadata["status"] = "archived"
    metadata["updated_at"] = now_iso()
    write_yaml(workspace / "metadata.yml", metadata)
    return archive_index


def main() -> int:
    parser = argparse.ArgumentParser(description="创建 Agentic-QA 需求工作区")
    parser.add_argument("slug", help="需求目录名，例如 demo-requirement")
    parser.add_argument("--prd-root", default="prd", help="PRD 根目录，默认 prd")
    parser.add_argument("--title", default=None, help="需求标题")
    args = parser.parse_args()

    workspace = create_workspace(args.slug, prd_root=args.prd_root, title=args.title)
    print(workspace.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
