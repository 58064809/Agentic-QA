from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from harness.registry import AgentRegistry, SkillRegistry, ToolRegistry  # noqa: E402
from harness.schemas.api_test_cases import API_CASES_SCHEMA_VERSION  # noqa: E402

CORE_FILES = (
    "README.md",
    "AGENTS.md",
    "COMMANDS.md",
    "docs/architecture.md",
    "docs/harness-contracts.md",
    "docs/review-gate.md",
    "docs/artifact-versioning.md",
    "docs/rag-design.md",
    "docs/roadmap.md",
    "src/harness/contracts.py",
    "src/harness/backend.py",
    "src/harness/engine.py",
    "src/harness/store.py",
    "src/harness/review.py",
)
EXCLUDED_PARTS = {
    ".git",
    ".codex",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime",
    "knowledge",
    "prd",
    "workspaces",
    "__pycache__",
}
INLINE_PATH = re.compile(r"`((?:src/harness|docs|scripts|tests)/[^`<>{}*?]+)`")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _validate_manifests(errors: list[str]) -> None:
    try:
        tools = ToolRegistry.builtin()
        skills = SkillRegistry.builtin()
        agents = AgentRegistry.builtin(skills=skills, tools=tools)
    except Exception as exc:
        errors.append(f"manifest 注册失败: {exc}")
        return
    if not agents.list() or not tools.list() or not skills.list():
        errors.append("Agent、Tool 和 Skill manifest 均不得为空")
    if "artifact.promote" in {tool for agent in agents.list() for tool in agent.tool_allowlist}:
        errors.append("artifact.promote 不得出现在任何 Agent allowlist")


def _validate_markdown_paths(root: Path, errors: list[str]) -> None:
    for path in root.rglob("*.md"):
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        for line_number, line in enumerate(_read(path).splitlines(), start=1):
            for token in INLINE_PATH.findall(line):
                normalized = token.rstrip(".,，。:：")
                if any(marker in normalized for marker in ("<", ">", "*")):
                    continue
                if not (root / normalized).exists():
                    errors.append(
                        f"{relative.as_posix()}:{line_number} 引用了不存在的路径: {normalized}"
                    )


def validate_docs_consistency(repo_root: Path) -> list[str]:
    root = repo_root.resolve()
    errors = [f"缺少核心文件: {path}" for path in CORE_FILES if not (root / path).is_file()]
    for legacy_root in (".runtime", "runtime", "rag", "apps", "integrations", "knowledge"):
        path = root / legacy_root
        if path.exists() and any(path.rglob("*.py")):
            errors.append(f"旧可执行链路仍存在: {legacy_root}/")
    _validate_manifests(errors)
    _validate_markdown_paths(root, errors)
    api_doc = root / "docs/api-test-generation.md"
    if api_doc.is_file() and API_CASES_SCHEMA_VERSION not in _read(api_doc):
        errors.append(
            f"docs/api-test-generation.md 未声明当前 API Cases Schema: {API_CASES_SCHEMA_VERSION}"
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 Harness 文档、manifest 和路径一致性")
    parser.add_argument("--repo-root", default=REPO_ROOT, type=Path)
    args = parser.parse_args()
    errors = validate_docs_consistency(args.repo_root)
    if not errors:
        print("文档一致性检查通过。")
        return 0
    print("文档一致性检查未通过：")
    for error in errors:
        print(f"- {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
