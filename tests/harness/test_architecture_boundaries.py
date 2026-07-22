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
