from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "harness"
EXTERNAL_INFRASTRUCTURE = ("langgraph", "psycopg", "openai", "mcp")
OUTER_LAYERS = (
    "harness.infrastructure",
    "harness.interfaces",
    "harness.bootstrap",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_domain_and_application_dependency_direction() -> None:
    violations: list[str] = []
    for layer in ("domain", "application"):
        for path in (PACKAGE_ROOT / layer).rglob("*.py"):
            forbidden = EXTERNAL_INFRASTRUCTURE + OUTER_LAYERS
            if layer == "domain":
                forbidden += ("harness.application",)
            for module in sorted(_imports(path)):
                if module.startswith(forbidden):
                    violations.append(f"{path.relative_to(PACKAGE_ROOT)} imports {module}")
    assert not violations, "架构依赖方向违规:\n- " + "\n- ".join(violations)


def test_public_package_does_not_export_v1_task_request() -> None:
    public_init = (PACKAGE_ROOT / "__init__.py").read_text(encoding="utf-8")
    contracts = (PACKAGE_ROOT / "contracts.py").read_text(encoding="utf-8")
    assert "TaskRequest" not in public_init
    assert "TaskRequest" not in contracts


def test_quality_adapters_do_not_live_in_domain() -> None:
    quality_root = PACKAGE_ROOT / "domain" / "quality"
    assert not any(quality_root.glob("*.py"))
    ports = (PACKAGE_ROOT / "application" / "ports.py").read_text(encoding="utf-8")
    assert "class QualityStrategy(Protocol)" in ports
    assert "class ArtifactNormalizer(Protocol)" in ports
    assert (PACKAGE_ROOT / "application" / "source" / "models.py").is_file()


def test_business_quality_pack_is_declarative_not_python() -> None:
    legacy = PACKAGE_ROOT / "infrastructure" / "quality" / "packs" / "city_opening_rewards"
    manifest = PACKAGE_ROOT / "manifests" / "quality" / "city-opening-rewards.yml"

    assert not any(legacy.glob("*.py"))
    assert manifest.is_file()


def test_workflow_model_calls_use_compiled_structured_prompts() -> None:
    engine_path = PACKAGE_ROOT / "infrastructure" / "workflow" / "engine.py"
    tree = ast.parse(engine_path.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "structured"
    ]

    assert calls
    for call in calls:
        keywords = {item.arg: item.value for item in call.keywords if item.arg}
        system = keywords["system"]
        prompt = keywords["prompt"]
        assert isinstance(system, ast.Attribute)
        assert system.attr == "content"
        assert isinstance(prompt, ast.Call)
        assert isinstance(prompt.func, ast.Attribute)
        assert prompt.func.attr == "user_message"


def test_candidate_has_no_persisted_quality_passed_field() -> None:
    models = (PACKAGE_ROOT / "domain" / "models.py").read_text(encoding="utf-8")
    tree = ast.parse(models)
    candidate = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ArtifactCandidate"
    )
    fields = {
        node.target.id
        for node in candidate.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert "quality_passed" not in fields
