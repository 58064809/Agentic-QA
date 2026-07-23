from __future__ import annotations

import re
from pathlib import Path

from harness.domain.schemas.api_test_cases import API_CASES_SCHEMA_VERSION
from harness.infrastructure.manifests.registry import AgentRegistry, SkillRegistry, ToolRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_FILES = (
    "README.md",
    "AGENTS.md",
    "COMMANDS.md",
    "docs/getting-started.md",
    "docs/cli-reference.md",
    "docs/agent-integration.md",
    "docs/architecture.md",
    "docs/configuration.md",
    "docs/harness-contracts.md",
    "docs/review-gate.md",
    "docs/artifact-versioning.md",
    "docs/rag-design.md",
    "docs/roadmap.md",
    "docs/schemas/api-cases.v1.1.schema.json",
    "docs/schemas/execution-evidence.v1.schema.json",
    "docs/schemas/failure-triage.v1.schema.json",
    "docs/schemas/agent-request.v1.schema.json",
    "docs/schemas/agent-request-result.v1.schema.json",
    "src/harness/schemas/agent-request.v1.schema.json",
    "src/harness/schemas/agent-request-result.v1.schema.json",
    "src/harness/contracts.py",
    "src/harness/backend.py",
    "src/harness/engine.py",
    "src/harness/store.py",
    "src/harness/review.py",
    "src/harness/domain/models.py",
    "src/harness/application/use_cases.py",
    "src/harness/infrastructure/persistence/filesystem.py",
    "src/harness/interfaces/facade.py",
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
INLINE_PATH = re.compile(r"`((?:src/harness|docs|tests)/[^`<>{}*?]+)`")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _manifest_errors() -> list[str]:
    try:
        tools = ToolRegistry.builtin()
        skills = SkillRegistry.builtin()
        agents = AgentRegistry.builtin(skills=skills, tools=tools)
    except Exception as exc:
        return [f"manifest 注册失败: {exc}"]
    errors = []
    if not agents.list() or not tools.list() or not skills.list():
        errors.append("Agent、Tool 和 Skill manifest 均不得为空")
    if "artifact.promote" in {tool for agent in agents.list() for tool in agent.tool_allowlist}:
        errors.append("artifact.promote 不得出现在任何 Agent allowlist")
    return errors


def _markdown_path_errors(root: Path) -> list[str]:
    errors = []
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
    return errors


def test_repository_contracts_are_consistent() -> None:
    root = REPO_ROOT.resolve()
    errors = [f"缺少核心文件: {path}" for path in CORE_FILES if not (root / path).is_file()]
    for legacy_root in (".runtime", "runtime", "rag", "apps", "integrations", "knowledge"):
        path = root / legacy_root
        if path.exists() and any(path.rglob("*.py")):
            errors.append(f"旧可执行链路仍存在: {legacy_root}/")
    errors.extend(_manifest_errors())
    errors.extend(_markdown_path_errors(root))
    api_doc = root / "docs/api-test-generation.md"
    if api_doc.is_file() and API_CASES_SCHEMA_VERSION not in _read(api_doc):
        errors.append(
            f"docs/api-test-generation.md 未声明当前 API Cases Schema: {API_CASES_SCHEMA_VERSION}"
        )

    docs_text = "\n".join(_read(path) for path in (root / "docs").glob("*.md"))
    for obsolete in (
        "TaskRequest",
        "Harness.run(",
        "Harness.stream(",
        "Harness.resume(",
        "Harness.inspect(",
        "agentic-qa.harness.*.v1",
    ):
        if obsolete in docs_text:
            errors.append(f"docs 仍包含旧公开契约: {obsolete}")

    assert not errors, "仓库一致性检查未通过：\n- " + "\n- ".join(errors)
