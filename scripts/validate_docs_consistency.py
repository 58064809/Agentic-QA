from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src"
for import_root in (str(REPO_ROOT), str(SOURCE_ROOT)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

from agentic_qa.contracts import AgentManifest, ToolManifest  # noqa: E402
from agentic_qa.schemas.api_test_cases import API_CASES_SCHEMA_VERSION  # noqa: E402

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
    "rules/artifact-path-rules.md",
    "src/agentic_qa/contracts.py",
    "src/agentic_qa/harness.py",
    "src/agentic_qa/engine.py",
    "src/agentic_qa/store.py",
    "src/agentic_qa/review.py",
)
EXCLUDED_PARTS = {
    ".git",
    ".agents",
    ".codex",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime",
    "prd",
    "__pycache__",
}
INLINE_PATH = re.compile(
    r"`((?:agentic_qa|docs|rules|prompts|knowledge|skills|scripts|tests)/[^`<>{}*?]+)`"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _validate_manifests(root: Path, errors: list[str]) -> None:
    agent_names: set[str] = set()
    for path in sorted((root / "src/agentic_qa/manifests/agents").glob("*.yml")):
        try:
            manifest = AgentManifest.model_validate(yaml.safe_load(_read(path)))
        except Exception as exc:
            errors.append(f"{path.relative_to(root).as_posix()} 无效: {exc}")
            continue
        if manifest.name in agent_names:
            errors.append(f"重复 Agent manifest: {manifest.name}")
        agent_names.add(manifest.name)
    if "qa_supervisor" not in agent_names:
        errors.append("缺少 qa_supervisor manifest")

    tool_names: set[str] = set()
    for path in sorted((root / "src/agentic_qa/manifests/tools").glob("*.yml")):
        try:
            manifest = ToolManifest.model_validate(yaml.safe_load(_read(path)))
        except Exception as exc:
            errors.append(f"{path.relative_to(root).as_posix()} 无效: {exc}")
            continue
        if manifest.name in tool_names:
            errors.append(f"重复 Tool manifest: {manifest.name}")
        tool_names.add(manifest.name)
    if "artifact.promote" not in tool_names:
        errors.append("缺少 artifact.promote manifest")


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
    if (root / "runtime/workflow").exists() or (root / "workflows/runtime").exists():
        errors.append("旧 WorkflowSpec 主链路仍存在")
    if (root / "runtime/cli").exists() or (root / "runtime/graph/app.py").exists():
        errors.append("旧 Runtime CLI 或 task facade 仍存在")
    _validate_manifests(root, errors)
    _validate_markdown_paths(root, errors)
    for path in (
        "docs/api-test-generation.md",
        "knowledge/automation/yaml-case-schema.md",
        "prompts/api-test-generation.md",
        "rules/automation-case-rules.md",
    ):
        target = root / path
        if target.is_file() and API_CASES_SCHEMA_VERSION not in _read(target):
            errors.append(f"{path} 未声明当前 API Cases Schema: {API_CASES_SCHEMA_VERSION}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 Harness 文档、manifest 和路径一致性")
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
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
