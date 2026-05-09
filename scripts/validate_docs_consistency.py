from __future__ import annotations

import argparse
import re
from pathlib import Path

CORE_FILES = [
    "README.md",
    "AGENTS.md",
    "COMMANDS.md",
    "rules/codex-output-rules.md",
    "knowledge/templates/codex-completion-summary-template.md",
    ".github/workflows/ci.yml",
    "docs/architecture/production-agent-runtime-roadmap.md",
    "docs/roadmap.md",
    "workflows/10-runtime-testcase-generation-workflow.md",
]
CORE_DIRS = [
    ".github",
    ".github/workflows",
    "docs",
    "docs/architecture",
    "workflows",
    "agents",
    "tasks",
    "prompts",
    "rules",
    "skills",
    "knowledge",
    "knowledge/templates",
    "prd",
    "scripts",
    "tests",
]
CODEX_OUTPUT_REQUIRED_TERMS = [
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
    "tasks/",
    "prompts/",
    "rules/",
    "skills/",
    "knowledge/",
    "docs/",
    "prd/",
    "scripts/",
    "tests/",
    "_codex_tasks/",
)
EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    ".deepeval",
    "agentic_qa.egg-info",
    "__pycache__",
}
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
PLANNED_REFERENCE_MARKERS = (
    "待生成",
    "如生成",
    "可后续生成",
    "后续生成",
    "可选新增",
    "后续任务中创建",
)
TASK_INSTRUCTION_REFERENCE_MARKERS = (" 中补充", "必须报告")


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
    if any(marker in token for marker in ("<", ">", "{", "}", "*", "?")):
        return True
    if re.search(r"\s", token):
        return True
    return False


def normalize_path_token(token: str) -> str:
    token = token.strip().strip(".,，。:：;；")
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
            if in_fenced_block:
                continue
            if any(marker in line for marker in PLANNED_REFERENCE_MARKERS):
                continue
            if source.startswith("_codex_tasks/") and any(
                marker in line for marker in TASK_INSTRUCTION_REFERENCE_MARKERS
            ):
                continue

            for match in INLINE_CODE_RE.finditer(line):
                token = normalize_path_token(match.group(1))
                if should_skip_path_token(token):
                    continue

                target = repo_root / token
                if not target.exists():
                    errors.append(f"{source}:{line_number} 引用了不存在的路径: {token}")
    return errors


def validate_docs_consistency(repo_root: Path) -> list[str]:
    repo_root = repo_root.resolve()
    errors: list[str] = []

    for relative_path in CORE_FILES:
        require_path(repo_root / relative_path, "核心文件", errors)

    for relative_path in CORE_DIRS:
        require_path(repo_root / relative_path, "核心目录", errors, directory=True)

    require_terms(
        repo_root / "rules/codex-output-rules.md",
        CODEX_OUTPUT_REQUIRED_TERMS,
        "Codex 输出规则",
        errors,
    )
    require_terms(
        repo_root / "knowledge/templates/codex-completion-summary-template.md",
        COMPLETION_TEMPLATE_REQUIRED_TERMS,
        "Codex 完成回执模板",
        errors,
    )
    errors.extend(find_broken_markdown_path_refs(repo_root))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验仓库文档结构和关键引用一致性")
    parser.add_argument(
        "--repo-root",
        default=Path(__file__).resolve().parents[1],
        type=Path,
        help="仓库根目录，默认按脚本所在位置推断",
    )
    args = parser.parse_args()

    errors = validate_docs_consistency(args.repo_root)
    if not errors:
        print("文档一致性检查通过。")
        return 0

    print("文档一致性检查失败:")
    for error in errors:
        print(f"- {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
