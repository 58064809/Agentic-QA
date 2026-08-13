from __future__ import annotations

import inspect
import json
import re
import shlex
from fnmatch import fnmatch
from pathlib import Path
from urllib.parse import unquote

import yaml

from harness.application.agent_request import AgentRequest, AgentRequestResult
from harness.domain.schemas.api_discovery import ApiDiscoveryCatalog, ApiDiscoveryExport
from harness.domain.schemas.api_test_cases import (
    API_CASES_SCHEMA_VERSION,
    LEGACY_API_CASES_SCHEMA_VERSION,
    ApiTestCasesDraft,
)
from harness.domain.schemas.execution_evidence import (
    EXECUTION_EVIDENCE_SCHEMA_VERSION,
    EXECUTION_EVIDENCE_V1_SCHEMA_VERSION,
    ExecutionEvidence,
)
from harness.domain.schemas.failure_triage import (
    FAILURE_TRIAGE_SCHEMA_VERSION,
    FAILURE_TRIAGE_V2_SCHEMA_VERSION,
    BugDraft,
    FailureTriage,
    FailureTriageV2,
)
from harness.domain.schemas.knowledge import RetrievalResult
from harness.domain.schemas.log_analysis import LogAnalysis
from harness.domain.schemas.log_evidence import LogEvidenceBundle
from harness.domain.schemas.qa_design import (
    RiskCatalogV2,
)
from harness.domain.schemas.qa_design import (
    TestCaseSetV2 as QATestCaseSetV2Contract,
)
from harness.domain.schemas.requirement_intelligence import (
    ImpactAnalysis,
    RequirementDelta,
)
from harness.domain.schemas.requirement_intelligence import (
    TestDesignPlan as DesignPlanContract,
)
from harness.domain.schemas.trace_analysis import RootCauseEvidenceGraph, TraceAnalysis
from harness.domain.schemas.trace_evidence import TraceEvidenceBundle
from harness.infrastructure.manifests.registry import KnowledgeRegistry, SkillRegistry
from harness.interfaces.cli import _parser
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
    "failure-triage.v2.schema.json": FailureTriageV2,
    "bug-draft.v1.schema.json": BugDraft,
    "log-evidence.v1.schema.json": LogEvidenceBundle,
    "log-analysis.v1.schema.json": LogAnalysis,
    "trace-evidence.v1.schema.json": TraceEvidenceBundle,
    "trace-analysis.v1.schema.json": TraceAnalysis,
    "root-cause-evidence-graph.v1.schema.json": RootCauseEvidenceGraph,
    "retrieval-result.v1.schema.json": RetrievalResult,
    "requirement-delta.v1.schema.json": RequirementDelta,
    "impact-analysis.v1.schema.json": ImpactAnalysis,
    "risk-catalog.v2.schema.json": RiskCatalogV2,
    "test-design-plan.v1.schema.json": DesignPlanContract,
    "test-case-set.v2.schema.json": QATestCaseSetV2Contract,
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
        if name.startswith("agent-request") or name in {
            "retrieval-result.v1.schema.json",
            "requirement-delta.v1.schema.json",
            "impact-analysis.v1.schema.json",
            "risk-catalog.v2.schema.json",
            "test-design-plan.v1.schema.json",
            "test-case-set.v2.schema.json",
        }:
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


def _documented_harness_commands() -> list[tuple[Path, str]]:
    commands: list[tuple[Path, str]] = []
    documents = [ROOT / "README.md", ROOT / "COMMANDS.md", *DOCS.rglob("*.md")]
    for document in documents:
        lines = document.read_text(encoding="utf-8").splitlines()
        index = 0
        while index < len(lines):
            line = lines[index].strip()
            if not line.startswith("python -m harness "):
                index += 1
                continue
            command = line.removeprefix("python -m harness ")
            while command.rstrip().endswith("`") and index + 1 < len(lines):
                command = command.rstrip()[:-1] + " " + lines[index + 1].strip()
                index += 1
            commands.append((document, command))
            index += 1
    return commands


def test_documented_cli_commands_are_accepted_by_current_parser() -> None:
    parser = _parser()
    errors: list[str] = []
    for document, command in _documented_harness_commands():
        normalized = re.sub(r"\[[^]]*]", "", command)
        normalized = re.sub(r"<[^>]+>", "example", normalized)
        try:
            parser.parse_args(shlex.split(normalized, posix=False))
        except SystemExit:
            errors.append(f"{document.relative_to(ROOT)}: {command}")
    assert not errors, "文档 CLI 示例与 argparse 不一致:\n- " + "\n- ".join(errors)


def test_capability_inventory_marks_current_and_legacy_contracts() -> None:
    payload = yaml.safe_load((DOCS / "capabilities.yml").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "agentic-qa.capabilities.v1"
    capabilities = payload["capabilities"]
    expected = {
        "api_generation": (
            API_CASES_SCHEMA_VERSION,
            LEGACY_API_CASES_SCHEMA_VERSION,
        ),
        "api_execution": (
            EXECUTION_EVIDENCE_SCHEMA_VERSION,
            EXECUTION_EVIDENCE_V1_SCHEMA_VERSION,
        ),
        "failure_triage": (
            FAILURE_TRIAGE_V2_SCHEMA_VERSION,
            FAILURE_TRIAGE_SCHEMA_VERSION,
        ),
    }
    for name, (current, legacy) in expected.items():
        item = capabilities[name]
        assert item["status"] == "implemented"
        assert item["current_contract"] == current
        assert item["legacy_read_only_contracts"] == [legacy]
        assert (DOCS / item["documentation"]).is_file()
    assert capabilities["bug_draft_review"]["external_issue_write"] is False


def test_high_risk_documentation_semantics_follow_runtime_contracts() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    api = (DOCS / "api-test-generation.md").read_text(encoding="utf-8")
    cli = (DOCS / "cli-reference.md").read_text(encoding="utf-8")
    config = (DOCS / "configuration.md").read_text(encoding="utf-8")
    getting_started = (DOCS / "getting-started.md").read_text(encoding="utf-8")
    triage = (DOCS / "failure-triage.md").read_text(encoding="utf-8")

    assert "新 API Candidate 只生成 `agentic-qa.api-cases.v1.2`" in agents
    assert "v1.1 仅供历史只读解释" in agents
    assert "只接受 `agentic-qa.api-cases.v1.1`" not in agents
    assert "mutation transport 前先以 `armed` 登记" in api
    assert "--allow-http-method GET" not in api
    assert "随后调用受限 `failure_triager` 模型" in cli
    assert "该命令不调用模型" not in cli
    assert "`allure-results`、HTML、Markdown 和报告汇总的返回路径以实际生成产物为准" in (
        getting_started
    )
    assert "工具列表为空" in triage
    assert "不会自动创建 Jira" in triage
    assert "现有 diff / Review Gate" in triage
    assert "api_key: secret://test_management.api_key" in config
    assert "cleanup_exempt_operations:" not in config
    rag = (DOCS / "rag-design.md").read_text(encoding="utf-8")
    architecture = (DOCS / "architecture.md").read_text(encoding="utf-8")
    assert "当前每批" not in rag
    assert "当前每批" not in architecture
    assert "有界 rule batch" in rag
    assert "有界 rule batch" in architecture


def test_canonical_local_config_keeps_secret_bearing_business_fields_as_references() -> None:
    payload = yaml.safe_load((ROOT / "agentic-qa.local.example.yml").read_text(encoding="utf-8"))
    environment = payload["api"]["services"]["member-service"]["environments"]["dev"]
    login = environment["auth"]["login"]
    references = [
        payload["system_database"]["password"],
        payload["runtime"]["cleanup_journal_key"],
        login["phone"],
        login["sms_code"],
        login["encryption"]["key"],
        environment["auth"]["fallback_token"],
    ]
    assert all(str(value).startswith("secret://") for value in references)
    assert "cleanup_exempt_operations" not in environment


def test_schema_index_has_one_current_and_one_legacy_entry_per_versioned_domain() -> None:
    index = (DOCS / "index.md").read_text(encoding="utf-8")
    entries = {
        "api-cases.v1.2.schema.json": "API cases v1.2",
        "api-cases.v1.1.schema.json": "API cases v1.1（历史读取）",
        "execution-evidence.v2.schema.json": "Execution evidence v2",
        "execution-evidence.v1.schema.json": "Execution evidence v1（只读兼容、已冻结）",
        "failure-triage.v2.schema.json": "Failure triage v2",
        "failure-triage.v1.schema.json": "Failure triage v1（只读兼容、已冻结）",
    }
    for filename, label in entries.items():
        assert index.count(f"({f'schemas/{filename}'})") == 1
        assert f"| {label} |" in index
