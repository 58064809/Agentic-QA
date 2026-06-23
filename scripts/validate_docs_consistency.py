from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from runtime.workflow.conditions import CONDITIONS
from runtime.workflow.loader import load_workflow_spec

CORE_FILES = [
    "README.md",
    "AGENTS.md",
    "COMMANDS.md",
    "rules/agent-output-rules.md",
    "knowledge/templates/agent-completion-summary-template.md",
    ".github/workflows/ci.yml",
    "docs/workflow-dsl.md",
    "docs/runtime-reliability.md",
    "docs/artifact-versioning.md",
    "docs/review-gate.md",
    "docs/artifact-standards.md",
    "docs/testcase-standards.md",
    "docs/rag-design.md",
    "docs/roadmap.md",
    "workflows/10-runtime-testcase-generation-workflow.md",
    "runtime/README.md",
    "skills/registry/skills.yaml",
]

CORE_DIRS = [
    ".github",
    ".github/workflows",
    "docs",
    "workflows",
    "agents",
    "prompts",
    "rules",
    "skills",
    "skills/registry",
    "skills/core",
    "skills/analysis",
    "skills/test-design",
    "skills/automation",
    "skills/reporting",
    "skills/knowledge",
    "knowledge",
    "knowledge/templates",
    "prd",
    "scripts",
    "tests",
    "runtime",
    "apps",
    "rag",
    "configs",
]

AGENT_OUTPUT_REQUIRED_TERMS = [
    "标准完成回执模板",
    "变更摘要",
    "修改文件",
    "验收结果",
    "待人工确认",
    "下一步建议",
]
COMPLETION_TEMPLATE_REQUIRED_TERMS = [
    "变更摘要",
    "修改文件",
    "验收结果",
    "待人工确认",
    "下一步建议",
    "未执行命令必须说明原因",
]
PATH_PREFIXES = (
    "workflows/",
    "agents/",
    "prompts/",
    "rules/",
    "skills/",
    "knowledge/",
    "docs/",
    "runtime/",
    "prd/",
    "scripts/",
    "tests/",
)
EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".atomcode",
    ".pytest_cache",
    ".ruff_cache",
    ".deepeval",
    "agentic_qa.egg-info",
    "__pycache__",
}
EXCLUDED_MARKDOWN_FILES = {"README_备份.md"}
EXCLUDED_MARKDOWN_DIRS = {"prd"}
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
PLANNED_REFERENCE_MARKERS = (
    "待生成",
    "待后续生成",
    "示例",
    "如生成",
    "可后续生成",
    "后续生成",
    "可选新增",
    "后续任务中创建",
)
TARGET_STATE_PATH_TOKENS = {
    "config/",
    "runtime/config/",
    "runtime/intent/",
    "runtime/workflow/",
    "runtime/rag/",
    "runtime/agents/",
    "integrations/",
}
RUNTIME_WORKFLOW_GLOB = "*.workflow.yml"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def require_path(path: Path, label: str, errors: list[str], *, directory: bool = False) -> None:
    exists = path.is_dir() if directory else path.is_file()
    if not exists:
        errors.append(f"缺少{label}: {path.as_posix()}")


def require_terms(path: Path, terms: list[str], label: str, errors: list[str]) -> None:
    if not path.is_file():
        return
    content = read_text(path)
    for term in terms:
        if term not in content:
            errors.append(f"{label}缺少关键内容: {term}")


def should_skip_path_token(token: str) -> bool:
    if not any(token == prefix.rstrip("/") or token.startswith(prefix) for prefix in PATH_PREFIXES):
        return True
    if any(marker in token for marker in ("XX-", "name-", "PRD-001")):
        return True
    if token in {"tests/utils/data.py"} or token.endswith("/report/qa-report.md"):
        return True
    if any(marker in token for marker in ("<", ">", "{", "}", "*", "?")):
        return True
    if re.search(r"\s", token):
        return True
    return False


def normalize_path_token(token: str) -> str:
    token = token.strip().rstrip(".,，。:：;；")
    if token.startswith("./"):
        token = token[2:]
    token = token.replace("\\", "/")
    if "#" in token:
        token = token.split("#", 1)[0]
    return token


def iter_markdown_files(repo_root: Path):
    for path in repo_root.rglob("*.md"):
        relative_parts = path.relative_to(repo_root).parts
        if any(part in EXCLUDED_DIRS for part in relative_parts):
            continue
        if any(part in EXCLUDED_MARKDOWN_DIRS for part in relative_parts):
            continue
        if path.name in EXCLUDED_MARKDOWN_FILES:
            continue
        yield path


def find_broken_markdown_path_refs(repo_root: Path) -> list[str]:
    errors: list[str] = []
    for markdown_path in iter_markdown_files(repo_root):
        source = markdown_path.relative_to(repo_root).as_posix()
        in_fenced_block = False
        for line_number, line in enumerate(read_text(markdown_path).splitlines(), start=1):
            if line.strip().startswith("```"):
                in_fenced_block = not in_fenced_block
                continue
            if in_fenced_block or any(marker in line for marker in PLANNED_REFERENCE_MARKERS):
                continue
            for match in INLINE_CODE_RE.finditer(line):
                token = normalize_path_token(match.group(1))
                if should_skip_path_token(token):
                    continue
                if source == "README.md" and token in TARGET_STATE_PATH_TOKENS:
                    continue
                if not (repo_root / token).exists():
                    errors.append(f"{source}:{line_number} 引用了不存在的路径: {token}")
    return errors


def validate_runtime_workflow_docs(repo_root: Path) -> list[str]:
    errors: list[str] = []
    docs_path = repo_root / "docs/workflow-dsl.md"
    workflow_dir = repo_root / "workflows/runtime"
    if not docs_path.is_file() or not workflow_dir.is_dir():
        return errors

    docs_content = read_text(docs_path)
    for workflow_path in sorted(workflow_dir.glob(RUNTIME_WORKFLOW_GLOB)):
        relative_path = workflow_path.relative_to(repo_root).as_posix()
        try:
            spec = load_workflow_spec(workflow_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{relative_path} 不是有效 Runtime Workflow DSL: {exc}")
            continue

        task_type = str(spec.state.get("task_type") or "")
        for token in (spec.id, relative_path, task_type):
            if token and f"`{token}`" not in docs_content:
                errors.append(f"docs/workflow-dsl.md 未列出 Runtime workflow 信息: {token}")

        raw = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
        for edge in raw.get("edges") or []:
            condition = edge.get("condition") if isinstance(edge, dict) else None
            if condition and condition not in CONDITIONS:
                errors.append(f"{relative_path} 使用了未注册 condition: {condition}")
            if condition and f"`{condition}`" not in docs_content:
                errors.append(f"docs/workflow-dsl.md 未列出 condition: {condition}")

    return errors


def validate_docs_consistency(repo_root: Path) -> list[str]:
    repo_root = repo_root.resolve()
    errors: list[str] = []
    for relative_path in CORE_FILES:
        require_path(repo_root / relative_path, "核心文件", errors)
    for relative_path in CORE_DIRS:
        require_path(repo_root / relative_path, "核心目录", errors, directory=True)
    require_terms(
        repo_root / "rules/agent-output-rules.md",
        AGENT_OUTPUT_REQUIRED_TERMS,
        "Agent 输出规则",
        errors,
    )
    require_terms(
        repo_root / "knowledge/templates/agent-completion-summary-template.md",
        COMPLETION_TEMPLATE_REQUIRED_TERMS,
        "Agent 完成回执模板",
        errors,
    )
    errors.extend(find_broken_markdown_path_refs(repo_root))
    errors.extend(validate_runtime_workflow_docs(repo_root))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验仓库文档结构和关键引用一致性")
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    args = parser.parse_args()
    errors = validate_docs_consistency(args.repo_root)
    if not errors:
        print("文档一致性检查通过。")
        return 0
    print("文档一致性检查未通过:")
    for error in errors:
        print(f"- {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
