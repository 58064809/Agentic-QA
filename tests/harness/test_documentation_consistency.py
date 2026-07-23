from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from urllib.parse import unquote

import yaml

from harness.application.agent_request import AgentRequest, AgentRequestResult
from harness.domain.schemas.api_test_cases import ApiTestCasesDraft
from harness.domain.schemas.execution_evidence import ExecutionEvidence
from harness.domain.schemas.failure_triage import FailureTriage
from harness.infrastructure.manifests.registry import SkillRegistry
from harness.interfaces.facade import Harness

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
LINK = re.compile(r"\[[^]]+]\(([^)]+)\)")
SCHEMAS = {
    "agent-request.v1.schema.json": AgentRequest,
    "agent-request-result.v1.schema.json": AgentRequestResult,
    "api-cases.v1.1.schema.json": ApiTestCasesDraft,
    "execution-evidence.v1.schema.json": ExecutionEvidence,
    "failure-triage.v1.schema.json": FailureTriage,
}
CONSUMED_ENV = {
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "AGENTIC_QA_MODEL_API_KEY_ENV",
    "AGENTIC_QA_MODEL",
    "AGENTIC_QA_MODEL_FLASH",
    "AGENTIC_QA_MODEL_PRO",
    "AGENTIC_QA_MODEL_BASE_URL",
    "AGENTIC_QA_MODEL_TIMEOUT_SECONDS",
    "AGENTIC_QA_BASE_URL",
    "RAG_API_KEY",
    "AGENTIC_QA_RAG_API_KEY_ENV",
    "AGENTIC_QA_RAG_BASE_URL",
    "PG_LOCAL_HOST",
    "PG_LOCAL_PORT",
    "PG_LOCAL_DATABASE",
    "PG_LOCAL_USER",
    "PG_LOCAL_PASSWORD",
}
RESERVED_ENV = {"GITHUB_TOKEN", "AGENTIC_QA_GITHUB_TOKEN_ENV"}


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
    assert "当前运行时没有 GitHub MCP adapter，不读取" in reference


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
    referenced = {reference for skill in skills.list() for reference in skill.references}
    knowledge = {path.name for path in (ROOT / "src/harness/knowledge").glob("*.md")}
    assert referenced == knowledge
    for name in knowledge:
        text = (ROOT / "src/harness/knowledge" / name).read_text(encoding="utf-8")
        assert text.startswith("# ")
        assert "\n## " in text
