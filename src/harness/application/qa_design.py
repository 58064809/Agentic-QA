from __future__ import annotations

import hashlib
import re

from harness.domain.schemas.qa_design import (
    BoundaryRequirement,
    EvidenceLevel,
    RequirementCatalog,
    RequirementRule,
    RiskCatalog,
    SourceReference,
    StateTransition,
    TestCase,
    TestCaseSet,
)
from harness.domain.schemas.requirement_intelligence import ImpactAnalysis, RequirementDelta

TESTCASE_HEADERS = (
    "用例ID",
    "需求/规则来源",
    "标题",
    "测试类型",
    "优先级",
    "前置条件",
    "测试数据",
    "测试步骤",
    "预期结果",
    "断言/证据",
    "待确认项",
)


def catalog_hash(catalog: RequirementCatalog) -> str:
    payload = catalog.model_dump_json(exclude_none=True)
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def render_requirement_catalog(catalog: RequirementCatalog) -> str:
    lines = [
        "---",
        "schema_version: agentic-qa.harness.artifact.v2",
        "artifact_type: requirement_analysis",
        "status: needs_human_review",
        "---",
        "",
        "# 需求分析候选",
        "",
        "## 来源清单",
        "",
    ]
    lines.extend(
        f"- `{item.source}`"
        + (f" / {item.section}" if item.section else "")
        + (f" / `{item.chunk_id}`" if item.chunk_id else "")
        for item in catalog.sources
    )
    if not catalog.sources:
        lines.append("- 无可确认来源。")
    sections = (
        ("参与者", catalog.actors),
        ("业务对象", catalog.business_objects),
        ("业务流程", catalog.flows),
    )
    for title, values in sections:
        lines.extend(["", f"## {title}", ""])
        lines.extend(f"- {value}" for value in values)
        if not values:
            lines.append("- 无已确认内容。")
    lines.extend(
        [
            "",
            "## 规则目录",
            "",
            "| 规则ID | 证据级别 | 标题 | 条件 | 结果 | 来源 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for rule in catalog.rules:
        refs = "<br>".join(
            _escape_cell(reference.source)
            + (f" / {_escape_cell(reference.section)}" if reference.section else "")
            for reference in rule.source_refs
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    rule.rule_id,
                    rule.evidence_level.value,
                    _escape_cell(rule.title),
                    _escape_cell(rule.condition),
                    _escape_cell(rule.outcome),
                    refs or "待确认",
                ]
            )
            + " |"
        )
    lines.extend(["", "## 边界与状态迁移", ""])
    boundary_lines: list[str] = []
    for rule in catalog.rules:
        for boundary in rule.boundaries:
            boundary_lines.append(
                f"- {rule.rule_id} / {boundary.field}: {', '.join(boundary.values)}"
            )
        for transition in rule.state_transitions:
            boundary_lines.append(
                f"- {rule.rule_id}: {transition.from_state} "
                f"--{transition.event}--> {transition.to_state}"
            )
    lines.extend(boundary_lines or ["- 无已确认边界或状态迁移。"])
    lines.extend(["", "## 冲突与歧义", ""])
    conflicts = [
        f"- {rule.rule_id} 与 {', '.join(rule.conflicts_with)} 存在冲突。"
        for rule in catalog.rules
        if rule.conflicts_with
    ]
    lines.extend(conflicts or ["- 无已识别冲突。"])
    lines.extend(["", "## 待确认项", ""])
    pending = [
        *catalog.pending_questions,
        *(
            f"{rule.rule_id}: {question}"
            for rule in catalog.rules
            for question in rule.pending_questions
        ),
    ]
    lines.extend(f"- {item}" for item in pending)
    if not pending:
        lines.append("- 无。")
    lines.extend(["", "## 测试影响", ""])
    lines.append(
        f"- 已确认规则 {len(catalog.confirmed_rule_ids)} 条；"
        "测试设计必须逐条覆盖已确认规则，并显式覆盖声明的边界与状态迁移。"
    )
    return "\n".join(lines) + "\n"


def render_testcase_set(testcase_set: TestCaseSet) -> str:
    lines = [
        "---",
        "schema_version: agentic-qa.harness.artifact.v2",
        "artifact_type: testcases",
        "status: needs_human_review",
        "---",
        "",
        "# 测试用例候选",
        "",
        "| " + " | ".join(TESTCASE_HEADERS) + " |",
        "|" + "|".join(["---"] * len(TESTCASE_HEADERS)) + "|",
    ]
    lines.extend(_render_case(case) for case in testcase_set.cases)
    lines.extend(
        [
            "",
            "## 覆盖矩阵",
            "",
            "| 规则/风险 | 用例 | 映射依据 |",
            "|---|---|---|",
        ]
    )
    for mapping in testcase_set.coverage:
        lines.append(
            "| "
            + " | ".join(
                [
                    mapping.rule_id,
                    ", ".join(mapping.case_ids),
                    _escape_cell(mapping.rationale),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def render_risk_catalog(catalog: RiskCatalog) -> str:
    lines = [
        "# 风险目录",
        "",
        "| 风险ID | 优先级 | 规则 | 风险 | 覆盖意图 |",
        "|---|---|---|---|---|",
    ]
    for risk in catalog.risks:
        lines.append(
            "| "
            + " | ".join(
                [
                    risk.risk_id,
                    risk.priority.value,
                    ", ".join(risk.rule_ids),
                    _escape_cell(f"{risk.title}：{risk.rationale}"),
                    "<br>".join(_escape_cell(item) for item in risk.coverage_intent),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def render_requirement_delta(delta: RequirementDelta) -> str:
    lines = [
        "---",
        "schema_version: agentic-qa.harness.artifact.v2",
        "artifact_type: requirement_delta",
        "status: needs_human_review",
        "---",
        "",
        "# Requirement Delta Candidate",
        "",
        "| Delta | Status | Old Rule | New Rule | Changed Fields | Evidence |",
        "|---|---|---|---|---|---|",
    ]
    for item in delta.items:
        lines.append(
            "| "
            + " | ".join(
                [
                    item.delta_id,
                    item.kind.value,
                    item.old_rule_id or "-",
                    item.new_rule_id or "-",
                    ", ".join(item.changed_fields) or "-",
                    "<br>".join(item.evidence_refs),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def render_impact_analysis(analysis: ImpactAnalysis) -> str:
    lines = [
        "---",
        "schema_version: agentic-qa.harness.artifact.v2",
        "artifact_type: impact_analysis",
        "status: needs_human_review",
        "---",
        "",
        "# Impact Analysis Candidate",
        "",
        "| Impact | Relation | Kind | Target | Confidence | Evidence | Reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for claim in analysis.claims:
        lines.append(
            "| "
            + " | ".join(
                [
                    claim.impact_id,
                    claim.relation,
                    claim.kind,
                    _escape_cell(claim.target),
                    f"{claim.confidence:.2f}",
                    "<br>".join(claim.evidence_refs),
                    _escape_cell(claim.reason),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def parse_testcase_markdown(content: str) -> TestCaseSet:
    lines = content.splitlines()
    expected_header = "| " + " | ".join(TESTCASE_HEADERS) + " |"
    try:
        header_index = lines.index(expected_header)
    except ValueError as exc:
        raise ValueError("testcases candidate has no exact ordered 11-column header row") from exc
    if header_index + 1 >= len(lines) or len(_split_row(lines[header_index + 1])) != 11:
        raise ValueError("testcases candidate has an invalid 11-column delimiter row")
    cases: list[TestCase] = []
    cursor = header_index + 2
    while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
        cells = _split_row(lines[cursor])
        if len(cells) != 11:
            raise ValueError(f"testcases row {cursor + 1} has {len(cells)} columns instead of 11")
        cases.append(
            TestCase(
                case_id=cells[0],
                rule_ids=_split_list(cells[1]),
                title=cells[2],
                test_type=cells[3],
                priority=cells[4],
                preconditions=_split_multivalue(cells[5]),
                test_data=_split_multivalue(cells[6]),
                steps=_split_multivalue(cells[7]),
                expected_results=_split_multivalue(cells[8]),
                assertions=_split_multivalue(cells[9]),
                pending_items=[] if cells[10] in {"", "无", "-"} else _split_multivalue(cells[10]),
            )
        )
        cursor += 1
    try:
        matrix_index = lines.index("## 覆盖矩阵")
    except ValueError as exc:
        raise ValueError("testcases candidate has no coverage matrix section") from exc
    matrix_rows = [line for line in lines[matrix_index + 1 :] if line.lstrip().startswith("|")]
    if len(matrix_rows) < 3:
        raise ValueError("coverage matrix has no mapping rows")
    from harness.domain.schemas.qa_design import CoverageMapping

    coverage = []
    for row in matrix_rows[2:]:
        cells = _split_row(row)
        if len(cells) != 3:
            raise ValueError("coverage matrix rows must have exactly 3 columns")
        coverage.append(
            CoverageMapping(
                rule_id=cells[0],
                case_ids=_split_list(cells[1]),
                rationale=cells[2],
            )
        )
    return TestCaseSet(cases=cases, coverage=coverage)


def parse_requirement_markdown(content: str) -> RequirementCatalog:
    lines = content.splitlines()
    rule_header = "| 规则ID | 证据级别 | 标题 | 条件 | 结果 | 来源 |"
    try:
        rule_header_index = lines.index(rule_header)
    except ValueError as exc:
        raise ValueError("requirement candidate has no deterministic rule table") from exc
    rules: list[RequirementRule] = []
    cursor = rule_header_index + 2
    while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
        cells = _split_row(lines[cursor])
        if len(cells) != 6:
            raise ValueError("requirement rule rows must have exactly 6 columns")
        refs = []
        for value in _split_multivalue(cells[5]):
            source, _, section = value.partition(" / ")
            if source not in {"待确认", "无"}:
                refs.append(
                    SourceReference(
                        source=source.strip("` "),
                        section=section or None,
                    )
                )
        rules.append(
            RequirementRule(
                rule_id=cells[0],
                evidence_level=EvidenceLevel(cells[1]),
                title=cells[2],
                condition=cells[3],
                outcome=cells[4],
                source_refs=refs,
            )
        )
        cursor += 1
    if not rules:
        raise ValueError("requirement candidate has no rule rows")
    rule_by_id = {rule.rule_id: rule for rule in rules}
    try:
        boundary_index = lines.index("## 边界与状态迁移")
        boundary_end = next(
            (
                index
                for index in range(boundary_index + 1, len(lines))
                if lines[index].startswith("## ")
            ),
            len(lines),
        )
    except ValueError:
        boundary_index = -1
        boundary_end = -1
    for line in lines[boundary_index + 1 : boundary_end]:
        value = line.removeprefix("- ").strip()
        if not value or value.startswith("无已确认"):
            continue
        transition_match = re.fullmatch(
            r"(?P<rule>[A-Z][A-Z0-9_-]*-\d{3,}): " r"(?P<from>.+) --(?P<event>.+)--> (?P<to>.+)",
            value,
        )
        if transition_match:
            rule_id = transition_match.group("rule")
            rule = rule_by_id.get(rule_id)
            if rule is not None:
                rule_by_id[rule_id] = rule.model_copy(
                    update={
                        "state_transitions": [
                            *rule.state_transitions,
                            StateTransition(
                                from_state=transition_match.group("from"),
                                event=transition_match.group("event"),
                                to_state=transition_match.group("to"),
                            ),
                        ]
                    }
                )
            continue
        boundary_match = re.fullmatch(
            r"(?P<rule>[A-Z][A-Z0-9_-]*-\d{3,}) / " r"(?P<field>[^:]+): (?P<values>.+)",
            value,
        )
        if boundary_match:
            rule_id = boundary_match.group("rule")
            rule = rule_by_id.get(rule_id)
            if rule is not None:
                rule_by_id[rule_id] = rule.model_copy(
                    update={
                        "boundaries": [
                            *rule.boundaries,
                            BoundaryRequirement(
                                field=boundary_match.group("field"),
                                values=[
                                    item.strip()
                                    for item in boundary_match.group("values").split(",")
                                ],
                            ),
                        ]
                    }
                )
    rules = [rule_by_id[rule.rule_id] for rule in rules]
    sources = list(
        {
            (reference.source, reference.section): reference
            for rule in rules
            for reference in rule.source_refs
        }.values()
    )
    return RequirementCatalog(sources=sources, rules=rules)


def _render_case(case: TestCase) -> str:
    values = [
        case.case_id,
        ", ".join(case.rule_ids),
        case.title,
        case.test_type,
        case.priority.value,
        "<br>".join(case.preconditions),
        "<br>".join(case.test_data),
        "<br>".join(f"{index}. {step}" for index, step in enumerate(case.steps, 1)),
        "<br>".join(case.expected_results),
        "<br>".join(case.assertions),
        "<br>".join(case.pending_items) if case.pending_items else "无",
    ]
    return "| " + " | ".join(_escape_cell(value) for value in values) + " |"


def _escape_cell(value: str) -> str:
    return re.sub(r"\r?\n", "<br>", value).replace("|", r"\|").strip()


def _split_row(line: str) -> list[str]:
    body = line.strip()
    if not body.startswith("|") or not body.endswith("|"):
        return []
    cells = re.split(r"(?<!\\)\|", body[1:-1])
    return [cell.strip().replace(r"\|", "|") for cell in cells]


def _split_list(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，]", value) if item.strip()]


def _split_multivalue(value: str) -> list[str]:
    values = [
        re.sub(r"^\d+[.)、]\s*", "", item).strip()
        for item in re.split(r"<br\s*/?>", value, flags=re.IGNORECASE)
    ]
    return [item for item in values if item]
