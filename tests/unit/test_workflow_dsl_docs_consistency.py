from __future__ import annotations

import re
from pathlib import Path

from runtime.workflow.conditions import CONDITIONS
from runtime.workflow.loader import load_workflow_spec

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_PATH = REPO_ROOT / "docs/workflow-dsl.md"
RUNTIME_WORKFLOW_DIR = REPO_ROOT / "workflows/runtime"


def docs_content() -> str:
    return DOCS_PATH.read_text(encoding="utf-8")


def extract_section_table(section_title: str) -> list[list[str]]:
    content = docs_content()
    match = re.search(
        rf"^#{{2,3}} {re.escape(section_title)}\n(?P<body>.*?)(?=^#{{2,3}} |\Z)",
        content,
        re.S | re.M,
    )
    assert match, f"docs/workflow-dsl.md 缺少章节: {section_title}"

    rows = []
    for line in match.group("body").splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        rows.append(cells)
    return rows[1:]


def real_runtime_workflow_rows() -> set[tuple[str, str, str]]:
    rows = set()
    for path in sorted(RUNTIME_WORKFLOW_DIR.glob("*.workflow.yml")):
        spec = load_workflow_spec(path)
        rows.add(
            (
                spec.id,
                path.relative_to(REPO_ROOT).as_posix(),
                str(spec.state.get("task_type") or ""),
            )
        )
    return rows


def real_runtime_conditions() -> set[str]:
    conditions = set()
    for path in sorted(RUNTIME_WORKFLOW_DIR.glob("*.workflow.yml")):
        spec = load_workflow_spec(path)
        conditions.update(edge.condition for edge in spec.edges if edge.condition)
    return conditions


def test_docs_runtime_workflow_table_matches_real_yaml_files():
    docs_rows = {tuple(row) for row in extract_section_table("当前 Runtime workflow 文件")}

    assert docs_rows == real_runtime_workflow_rows()


def test_docs_condition_table_matches_registered_conditions():
    docs_rows = extract_section_table("当前内置 condition")
    docs_conditions = {row[0] for row in docs_rows}

    assert docs_conditions == set(CONDITIONS)


def test_real_runtime_yaml_conditions_are_documented_and_registered():
    used_conditions = real_runtime_conditions()

    assert used_conditions <= set(CONDITIONS)
    assert used_conditions <= {row[0] for row in extract_section_table("当前内置 condition")}
