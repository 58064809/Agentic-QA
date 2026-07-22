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


def test_city_quality_pack_stays_split() -> None:
    root = PACKAGE_ROOT / "infrastructure" / "quality" / "packs" / "city_opening_rewards"
    required = {"parser.py", "rules.py", "validators.py", "normalizer.py", "strategy.py"}
    assert required.issubset({path.name for path in root.glob("*.py")})
    oversized = {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in root.glob("*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > 1100
    }
    assert not oversized, f"city quality pack 出现新的单文件聚合实现: {oversized}"


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
