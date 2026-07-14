from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import yaml

from runtime.workflow.catalog import (
    ANALYSIS_CONTEXT_FILES,
    API_DISCOVERY_CONTEXT_FILES,
    API_TEST_CONTEXT_FILES,
    BASE_CONTEXT_FILES,
    QA_REPORT_CONTEXT_FILES,
    RAG_AUTOMATION_CASE_CONTEXT_FILES,
    TESTCASE_CONTEXT_FILES,
    UI_TEST_CONTEXT_FILES,
)
from runtime.workflow.conditions import CONDITIONS
from runtime.workflow.loader import load_workflow_spec
from runtime.workspace import ARTIFACT_PREVIEW_FILES, ARTIFACT_SPECS

CORE_FILES = [
    "README.md",
    "AGENTS.md",
    "COMMANDS.md",
    "rules/agent-output-rules.md",
    "rules/artifact-path-rules.md",
    "knowledge/templates/agent-completion-summary-template.md",
    ".github/workflows/ci.yml",
    "docs/architecture.md",
    "docs/workflow-dsl.md",
    "docs/runtime-reliability.md",
    "docs/artifact-versioning.md",
    "docs/review-gate.md",
    "docs/artifact-standards.md",
    "docs/testcase-standards.md",
    "docs/prompt-engineering.md",
    "docs/rag-design.md",
    "docs/roadmap.md",
    "runtime/README.md",
    "runtime/workspace.py",
    "runtime/workflow/catalog.py",
    "skills/registry/skills.yaml",
]

CORE_DIRS = [
    ".github",
    ".github/workflows",
    "docs",
    "workflows",
    "workflows/runtime",
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
    ".agents",
    ".codex",
    ".idea",
    ".atomcode",
    ".pytest_cache",
    ".ruff_cache",
    ".deepeval",
    ".runtime",
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
LEGACY_WORKFLOW_RE = re.compile(r"^workflows/\d{2}-.+-workflow\.md$")
LEGACY_CONTRACT_TOKENS = {
    "workspace.yml": "metadata.yml",
    "/analysis/": "artifacts/requirement-analysis.md",
    "/cases/": "artifacts/testcases.md",
    "/execution/": "artifacts/ 或 .runtime/runs/",
    "/defects/": "artifacts/",
    "/report/": "artifacts/qa-report.md",
    "test-cases.md": "testcases.md",
    "qa-review.md": "qa-report.preview.md",
}
NEGATIVE_REFERENCE_MARKERS = (
    "禁止",
    "废弃",
    "旧路径",
    "旧目录",
    "旧文件",
    "不支持",
    "不保留",
    "不得继续",
    "不得使用",
    "删除",
    "移除",
)
CONTRACT_SCAN_ROOTS = (
    "README.md",
    "AGENTS.md",
    "COMMANDS.md",
    "docs",
    "rules",
    "prompts",
    "agents",
    "skills",
    "workflows",
    "configs",
    "runtime/workflow/catalog.py",
)
CONTRACT_SCAN_SUFFIXES = {".md", ".yml", ".yaml", ".py", ".toml"}
PROMPT_CANONICALS = {
    "prompts/api-test-generation-prompt.md": ("prompts/api-test-generation.md",),
    "prompts/ui-test-generation-prompt.md": ("prompts/ui-test-generation.md",),
}
RUNTIME_CONTEXT_GROUPS = (
    BASE_CONTEXT_FILES,
    ANALYSIS_CONTEXT_FILES,
    TESTCASE_CONTEXT_FILES,
    API_TEST_CONTEXT_FILES,
    RAG_AUTOMATION_CASE_CONTEXT_FILES,
    UI_TEST_CONTEXT_FILES,
    API_DISCOVERY_CONTEXT_FILES,
    QA_REPORT_CONTEXT_FILES,
)


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


def iter_contract_files(repo_root: Path):
    seen: set[Path] = set()
    for entry in CONTRACT_SCAN_ROOTS:
        path = repo_root / entry
        candidates = [path] if path.is_file() else path.rglob("*") if path.is_dir() else []
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.lower() not in CONTRACT_SCAN_SUFFIXES:
                continue
            relative_parts = candidate.relative_to(repo_root).parts
            if any(part in EXCLUDED_DIRS or part == "prd" for part in relative_parts):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            yield candidate


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


def find_legacy_workflow_docs(repo_root: Path) -> list[str]:
    errors: list[str] = []
    workflow_dir = repo_root / "workflows"
    if not workflow_dir.is_dir():
        return errors
    for path in sorted(workflow_dir.glob("*.md")):
        relative = path.relative_to(repo_root).as_posix()
        if LEGACY_WORKFLOW_RE.fullmatch(relative):
            errors.append(f"存在旧 Workflow Markdown，必须删除并使用 workflows/runtime/*.workflow.yml: {relative}")
    return errors


def find_legacy_contract_refs(repo_root: Path) -> list[str]:
    errors: list[str] = []
    for path in iter_contract_files(repo_root):
        source = path.relative_to(repo_root).as_posix()
        for line_number, line in enumerate(read_text(path).splitlines(), start=1):
            if any(marker in line for marker in NEGATIVE_REFERENCE_MARKERS):
                continue
            for token, replacement in LEGACY_CONTRACT_TOKENS.items():
                if token in line:
                    errors.append(
                        f"{source}:{line_number} 仍引用旧契约 {token!r}，应改为 {replacement}"
                    )
            for match in re.finditer(r"workflows/\d{2}-[^\s`'\"]+-workflow\.md", line):
                errors.append(
                    f"{source}:{line_number} 仍引用旧 Workflow 文档: {match.group(0)}"
                )
    return errors


def validate_prompt_uniqueness(repo_root: Path) -> list[str]:
    errors: list[str] = []
    for canonical, duplicates in PROMPT_CANONICALS.items():
        if not (repo_root / canonical).is_file():
            errors.append(f"缺少当前 Prompt 权威文件: {canonical}")
        for duplicate in duplicates:
            if (repo_root / duplicate).exists():
                errors.append(f"存在重复 Prompt 正文: {duplicate}；权威文件为 {canonical}")
    return errors


def validate_runtime_context_files(repo_root: Path) -> list[str]:
    errors: list[str] = []
    context_files = sorted({path for group in RUNTIME_CONTEXT_GROUPS for path in group})
    for relative in context_files:
        if LEGACY_WORKFLOW_RE.fullmatch(relative):
            errors.append(f"Runtime 上下文仍加载旧 Workflow 文档: {relative}")
        if not (repo_root / relative).is_file():
            errors.append(f"Runtime 上下文引用不存在的文件: {relative}")
    return errors


def validate_workspace_contract_docs(repo_root: Path) -> list[str]:
    errors: list[str] = []
    rules_path = repo_root / "rules/artifact-path-rules.md"
    if not rules_path.is_file():
        return errors
    content = read_text(rules_path)
    for artifact_key, spec in ARTIFACT_SPECS.items():
        expected = {
            spec["current_path"],
            spec["review_path"],
            spec["history_index"],
            f"runs/<run-id>/{ARTIFACT_PREVIEW_FILES[artifact_key]}",
        }
        for token in expected:
            if token not in content:
                errors.append(f"rules/artifact-path-rules.md 未覆盖 Runtime 路径契约: {token}")
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

        raw = yaml.safe_load(workflow_path.read_text(encoding="utf-8-sig")) or {}
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
    errors.extend(find_legacy_workflow_docs(repo_root))
    errors.extend(find_legacy_contract_refs(repo_root))
    errors.extend(validate_prompt_uniqueness(repo_root))
    errors.extend(validate_runtime_context_files(repo_root))
    errors.extend(validate_workspace_contract_docs(repo_root))
    errors.extend(validate_runtime_workflow_docs(repo_root))
    return errors


def print_result(errors: list[str]) -> int:
    if not errors:
        print("文档与契约一致性检查通过。")
        return 0
    print("文档与契约一致性检查未通过:")
    for error in errors:
        print(f"- {error}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="校验仓库文档、Workflow、Prompt 与 Runtime 契约一致性")
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument("--watch", action="store_true", help="循环检查，文件修复后自动重新验证")
    parser.add_argument("--interval", type=float, default=2.0, help="watch 模式检查间隔，单位秒")
    args = parser.parse_args()

    if not args.watch:
        return print_result(validate_docs_consistency(args.repo_root))

    try:
        while True:
            print_result(validate_docs_consistency(args.repo_root))
            time.sleep(max(args.interval, 0.2))
    except KeyboardInterrupt:
        print("已停止循环检查。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
