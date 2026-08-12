from __future__ import annotations

import inspect
import json
import re
from fnmatch import fnmatch
from pathlib import Path
from urllib.parse import unquote

import yaml

from harness.application.agent_request import AgentRequest, AgentRequestResult
from harness.domain.schemas.api_discovery import ApiDiscoveryCatalog, ApiDiscoveryExport
from harness.domain.schemas.api_test_cases import ApiTestCasesDraft
from harness.domain.schemas.execution_evidence import ExecutionEvidence
from harness.domain.schemas.failure_triage import FailureTriage
from harness.domain.schemas.log_evidence import LogEvidenceBundle
from harness.infrastructure.manifests.registry import KnowledgeRegistry, SkillRegistry
from harness.interfaces.facade import Harness

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
LINK = re.compile(r"\[[^]]+]\(([^)]+)\)")
DIRECTIVE = re.compile(r"必须|不得|禁止|只允许|不能|不允许|应当|务必|不要|只能|不可")
SCHEMAS = {
    "api-discovery.v1.1.schema.json": ApiDiscoveryCatalog,
    "api-discovery-export.v1.schema.json": ApiDiscoveryExport,
    "agent-request.v1.schema.json": AgentRequest,
    "agent-request-result.v1.schema.json": AgentRequestResult,
    "api-cases.v1.2.schema.json": ApiTestCasesDraft,
    "execution-evidence.v2.schema.json": ExecutionEvidence,
    "failure-triage.v1.schema.json": FailureTriage,
    "log-evidence.v1.schema.json": LogEvidenceBundle,
}
CONSUMED_ENV = {
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "RAG_API_KEY",
}
RESERVED_ENV: set[str] = set()


class _MkDocsLoader(yaml.SafeLoader):
    """Parse MkDocs Python-name tags without importing documentation plugins."""


_MkDocsLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/name:",
    lambda _loader, suffix, _node: suffix,
)


def _nav_paths(value: object) -> set[str]:
    if isinstance(value, str):
        return {value} if value.endswith(".md") else set()
    if isinstance(value, list):
        return set().union(*(_nav_paths(item) for item in value), set())
    if isinstance(value, dict):
        return set().union(*(_nav_paths(item) for item in value.values()), set())
    return set()


def test_mkdocs_navigation_covers_every_markdown_page() -> None:
    config = yaml.load(
        (ROOT / "mkdocs.yml").read_text(encoding="utf-8"),
        Loader=_MkDocsLoader,
    )
    actual = {path.relative_to(DOCS).as_posix() for path in DOCS.rglob("*.md")}
    assert _nav_paths(config["nav"]) == actual


def test_local_markdown_links_resolve() -> None:
    errors: list[str] = []
    for document in [ROOT / "README.md", ROOT / "COMMANDS.md", *DOCS.rglob("*.md")]:
        for target in LINK.findall(document.read_text(encoding="utf-8")):
            target = unquote(target.split("#", 1)[0])
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (document.parent / target).resolve()
            if not resolved.exists():
                errors.append(f"{document.relative_to(ROOT)} -> {target}")
    assert not errors, "无效本地文档链接:\n- " + "\n- ".join(errors)


def test_harness_contract_table_covers_public_facade() -> None:
    public = {
        name
        for name, function in inspect.getmembers(Harness, inspect.isfunction)
        if not name.startswith("_")
    }
    document = (DOCS / "harness-contracts.md").read_text(encoding="utf-8")
    documented = {name for name in public if f"| `{name}` |" in document}
    assert documented == public
    assert "不是 Facade 契约" in document


def test_environment_reference_is_complete_and_marks_reserved_values() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    configured = {
        line.split("=", 1)[0]
        for line in example.splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    assert CONSUMED_ENV | RESERVED_ENV <= configured
    reference = (DOCS / "configuration.md").read_text(encoding="utf-8")
    for name in CONSUMED_ENV | RESERVED_ENV:
        assert f"`{name}`" in reference
    assert "`agentic-qa.local.yml`" in reference


def test_checked_in_json_schemas_match_pydantic_models() -> None:
    for name, model in SCHEMAS.items():
        actual = json.loads((DOCS / "schemas" / name).read_text(encoding="utf-8"))
        assert actual == model.model_json_schema(), name
        if name.startswith("agent-request"):
            packaged = json.loads(
                (ROOT / "src" / "harness" / "schemas" / name).read_text(encoding="utf-8")
            )
            assert packaged == actual, name


def test_runtime_knowledge_is_structured_and_referenced() -> None:
    skills = SkillRegistry.builtin()
    referenced = {reference for skill in skills.list() for reference in skill.knowledge_refs}
    knowledge_registry = KnowledgeRegistry.builtin()
    knowledge = {item.name for item in knowledge_registry.list()}
    assert referenced == knowledge
    assert not list((ROOT / "src/harness/knowledge").glob("*.md"))
    assert all(item.deterministic_checks for item in knowledge_registry.list())


def test_content_audience_catalog_is_exhaustive_and_unambiguous() -> None:
    catalog = yaml.safe_load((ROOT / "content-audiences.yml").read_text(encoding="utf-8"))
    entries = catalog["entries"]
    tracked = {
        "README.md",
        "COMMANDS.md",
        "AGENTS.md",
        "content-audiences.yml",
        *(
            path.relative_to(ROOT).as_posix()
            for root in [
                ROOT / "docs",
                ROOT / "src/harness/manifests",
                ROOT / "src/harness/knowledge",
                ROOT / "src/harness/schemas",
                ROOT / "src/harness/domain/schemas",
            ]
            for path in root.rglob("*")
            if path.is_file() and path.suffix in {".md", ".yml", ".json", ".py"}
        ),
        "src/harness/domain/models.py",
    }
    for path in sorted(tracked):
        matches = [entry for entry in entries if fnmatch(path, entry["pattern"])]
        assert len(matches) == 1, (path, matches)
        assert matches[0]["audience"] in catalog["audiences"]


def test_local_document_links_follow_content_audience_boundaries() -> None:
    catalog = yaml.safe_load((ROOT / "content-audiences.yml").read_text(encoding="utf-8"))
    entries = catalog["entries"]

    def audience(path: Path) -> str:
        relative = path.relative_to(ROOT).as_posix()
        matches = [entry for entry in entries if fnmatch(relative, entry["pattern"])]
        assert len(matches) == 1, relative
        return str(matches[0]["audience"])

    violations: list[str] = []
    for document in [ROOT / "README.md", ROOT / "COMMANDS.md", *DOCS.rglob("*.md")]:
        source_audience = audience(document)
        allowed = set(catalog["audiences"][source_audience]["may_reference"])
        for target in LINK.findall(document.read_text(encoding="utf-8")):
            target = unquote(target.split("#", 1)[0])
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (document.parent / target).resolve()
            target_audience = audience(resolved)
            if target_audience not in allowed:
                violations.append(
                    f"{document.relative_to(ROOT)} ({source_audience}) -> "
                    f"{resolved.relative_to(ROOT)} ({target_audience})"
                )
    assert not violations, "跨内容层引用:\n- " + "\n- ".join(violations)


def test_runtime_ai_assets_do_not_reference_human_docs() -> None:
    for path in [
        *(ROOT / "src/harness/manifests").rglob("*.yml"),
        *(ROOT / "src/harness/knowledge").rglob("*.yml"),
    ]:
        text = path.read_text(encoding="utf-8")
        assert "docs/" not in text
        assert "README.md" not in text
        assert "AGENTS.md" not in text


def test_human_documentation_describes_behavior_without_directive_language() -> None:
    documents = [ROOT / "README.md", ROOT / "COMMANDS.md", *DOCS.rglob("*.md")]
    violations: list[str] = []
    for document in documents:
        text = document.read_text(encoding="utf-8")
        prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        for line_number, line in enumerate(prose.splitlines(), 1):
            if DIRECTIVE.search(line):
                violations.append(f"{document.relative_to(ROOT)}:{line_number}: {line.strip()}")
    assert not violations, "人类文档包含命令式规则语言:\n- " + "\n- ".join(violations)
