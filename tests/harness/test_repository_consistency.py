from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from harness.domain.schemas.api_test_cases import API_CASES_SCHEMA_VERSION
from harness.infrastructure.manifests.registry import AgentRegistry, SkillRegistry, ToolRegistry
from harness.infrastructure.prompts import PromptCompiler

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_FILES = (
    "README.md",
    "AGENTS.md",
    "COMMANDS.md",
    "constraints.txt",
    "content-audiences.yml",
    "pyproject.toml",
    "scripts/cold-start-check.ps1",
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
    "docs/schemas/api-cases.v1.2.schema.json",
    "docs/schemas/execution-evidence.v1.schema.json",
    "docs/schemas/execution-evidence.v2.schema.json",
    "docs/schemas/failure-triage.v1.schema.json",
    "docs/schemas/failure-triage.v2.schema.json",
    "docs/schemas/bug-draft.v1.schema.json",
    "docs/schemas/log-evidence.v1.schema.json",
    "docs/schemas/log-analysis.v1.schema.json",
    "docs/schemas/trace-evidence.v1.schema.json",
    "docs/schemas/trace-analysis.v1.schema.json",
    "docs/schemas/root-cause-evidence-graph.v1.schema.json",
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
    "src/harness/infrastructure/prompts/compiler.py",
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
RELEASED_API_CASE_SCHEMAS = {
    "api-cases.v1.1.schema.json": (
        "agentic-qa.api-cases.v1.1",
        "e8a6cd47c49bce25b4161a15751607ba4d8af2c644e6e7165f8b2228a0a39c25",
    ),
    "api-cases.v1.2.schema.json": (
        "agentic-qa.api-cases.v1.2",
        "9033ab5e02d6d7789411d4c41929899714e22967fa8dd318db98773fbf2589d2",
    ),
}
RELEASED_EVIDENCE_SCHEMAS = {
    "execution-evidence.v1.schema.json": (
        "agentic-qa.execution-evidence.v1",
        "f8ff4fc8227cb4df1eeb46edcb8be72223796fe1556c8a2c87ebeee887292278",
    ),
    "failure-triage.v1.schema.json": (
        "agentic-qa.failure-triage.v1",
        "459c60e6992d04e4c2675686a68eb27229dca3026556a9e56d7c1a5d3a8a53e6",
    ),
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _manifest_errors() -> list[str]:
    try:
        tools = ToolRegistry.builtin()
        skills = SkillRegistry.builtin()
        agents = AgentRegistry.builtin(skills=skills, tools=tools)
        PromptCompiler(agents=agents, skills=skills)
    except Exception as exc:
        return [f"manifest 注册失败: {exc}"]
    errors = []
    if not agents.list() or not tools.list() or not skills.list():
        errors.append("Agent、Tool 和 Skill manifest 均不得为空")
    if "artifact.promote" in {tool for agent in agents.list() for tool in agent.tool_allowlist}:
        errors.append("artifact.promote 不得出现在任何 Agent allowlist")
    return errors


def test_released_api_case_schemas_are_byte_for_byte_immutable() -> None:
    for name, (version, expected_sha256) in RELEASED_API_CASE_SCHEMAS.items():
        content = (REPO_ROOT / "docs" / "schemas" / name).read_bytes()
        assert hashlib.sha256(content).hexdigest() == expected_sha256, name
        schema = json.loads(content)
        assert schema["properties"]["schema_version"]["const"] == version


def test_released_evidence_schemas_are_byte_for_byte_immutable() -> None:
    for name, (version, expected_sha256) in RELEASED_EVIDENCE_SCHEMAS.items():
        content = (REPO_ROOT / "docs" / "schemas" / name).read_bytes()
        normalized = content.replace(b"\r\n", b"\n")
        assert b"\r" not in normalized, name
        assert hashlib.sha256(normalized).hexdigest() == expected_sha256, name
        schema = json.loads(content)
        assert schema["properties"]["schema_version"]["const"] == version


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

    pyproject = _read(root / "pyproject.toml")
    constraints = _read(root / "constraints.txt")
    cold_start_script = _read(root / "scripts/cold-start-check.ps1")
    nightly = _read(root / ".github/workflows/nightly-live-eval.yml")
    ci = _read(root / ".github/workflows/ci.yml")
    if '"build>=1,<2"' not in pyproject or "build==" not in constraints:
        errors.append("wheel 构建工具未同时声明在 dev 依赖与 constraints")
    if "--index-url" in constraints or "--trusted-host" in constraints:
        errors.append("constraints 不得固定本机 Python 包索引")
    if '"config", "doctor"' not in cold_start_script:
        errors.append("冷启动运行时检查未调用统一配置 doctor")
    if "FilesystemLocalConfigLoader('.')" not in cold_start_script:
        errors.append("冷启动数据库检查未从统一配置加载连接参数")
    if "PG_LOCAL_" in cold_start_script or "AGENTIC_QA_MODEL_" in cold_start_script:
        errors.append("冷启动检查仍引用已移除的环境变量配置")
    if '".[dev,docs]" -c constraints.txt' not in _read(root / "README.md"):
        errors.append("fresh clone 安装未包含冷启动完整依赖与 constraints")
    for marker in (
        "order-lifecycle",
        "api_test_draft/raw.yml",
        '".[dev]" -c constraints.txt',
    ):
        if marker not in nightly:
            errors.append(f"Nightly API Live Eval 缺少配置: {marker}")

    if ci.count("-c constraints.txt") < 2 or "cache-dependency-path: constraints.txt" not in ci:
        errors.append("CI dependency installation is not locked by constraints.txt")

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
