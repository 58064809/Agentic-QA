from __future__ import annotations

import csv
import io
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from harness.application.qa_design import TESTCASE_HEADERS
from harness.application.source import SourceBundle
from harness.domain.models import ApiScenarioSourceFile, ApiScenarioSourceSummary
from harness.domain.schemas.openapi import OpenApiInspection
from harness.domain.schemas.qa_design import CoverageMapping, TestCase, TestCaseSet
from harness.infrastructure.tools.openapi import inspect_openapi


class ManualTestCaseSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str
    case: TestCase


class ApiScenarioSourceInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: ApiScenarioSourceSummary
    openapi: tuple[OpenApiInspection, ...]
    manual_cases: tuple[ManualTestCaseSource, ...]

    @property
    def recognized_paths(self) -> tuple[str, ...]:
        return tuple(
            [item.path for item in self.summary.openapi_files]
            + [item.path for item in self.summary.manual_case_files]
        )

    def model_tool_results(self) -> list[dict[str, Any]]:
        results = [
            {"tool": "openapi.inspect", "result": item.model_dump(mode="json")}
            for item in self.openapi
        ]
        results.append(
            {
                "tool": "manual-test-cases.inspect",
                "result": {
                    "schema_version": "agentic-qa.manual-test-cases-inspection.v1",
                    "cases": [
                        {
                            "source_path": item.source_path,
                            **item.case.model_dump(mode="json", exclude_none=True),
                        }
                        for item in self.manual_cases
                    ],
                },
            }
        )
        return results


class FilesystemApiScenarioSourceCatalog:
    def __init__(self, source_bundles: Any) -> None:
        self._source_bundles = source_bundles

    def inspect(self, workspace: str, run_id: str) -> ApiScenarioSourceSummary:
        bundle = self._source_bundles.load_source_bundle(workspace, run_id)
        return inspect_api_scenario_sources(bundle).summary


def inspect_api_scenario_sources(
    bundle: SourceBundle,
    *,
    require_complete: bool = True,
) -> ApiScenarioSourceInspection:
    openapi_files: list[ApiScenarioSourceFile] = []
    manual_files: list[ApiScenarioSourceFile] = []
    ignored_files: list[ApiScenarioSourceFile] = []
    inspections: list[OpenApiInspection] = []
    manual_cases: list[ManualTestCaseSource] = []

    for document in bundle.documents:
        if document.text is None:
            ignored_files.append(
                ApiScenarioSourceFile(
                    path=document.path,
                    kind="ignored",
                    reason="source is not complete readable UTF-8 text",
                )
            )
            continue
        path = document.path
        suffix = PurePosixPath(path).suffix.casefold()
        text = document.text.removeprefix("\ufeff")
        parsed = _parse_yaml_or_json(text, path=path, suffix=suffix)
        if isinstance(parsed, dict) and ("openapi" in parsed or "swagger" in parsed):
            inspection = inspect_openapi(parsed, source=path)
            inspections.append(inspection)
            openapi_files.append(ApiScenarioSourceFile(path=path, kind="openapi"))
            continue
        if isinstance(parsed, dict) and parsed.get("schema_version") == (
            "agentic-qa.test-case-set.v1"
        ):
            testcase_set = TestCaseSet.model_validate(parsed)
            _append_manual_source(path, testcase_set, manual_files, manual_cases)
            continue
        if suffix == ".csv":
            testcase_set = _parse_csv_testcases(text, path=path)
            _append_manual_source(path, testcase_set, manual_files, manual_cases)
            continue
        if suffix in {".md", ".markdown"}:
            testcase_set = _parse_markdown_testcases(text, path=path)
            if testcase_set is not None:
                _append_manual_source(path, testcase_set, manual_files, manual_cases)
                continue
        ignored_files.append(
            ApiScenarioSourceFile(
                path=path,
                kind="ignored",
                reason="not a complete OpenAPI document or supported 11-column test-case file",
            )
        )

    case_ids = [item.case.case_id for item in manual_cases]
    duplicates = sorted(case_id for case_id in set(case_ids) if case_ids.count(case_id) > 1)
    if duplicates:
        raise ValueError(f"manual test case IDs must be globally unique: {duplicates}")
    if require_complete and not openapi_files:
        raise ValueError("api prepare requires at least one complete OpenAPI/Swagger document")
    if require_complete and not manual_files:
        raise ValueError("api prepare requires at least one valid manual test-case file")
    summary = ApiScenarioSourceSummary(
        openapi_files=openapi_files,
        manual_case_files=manual_files,
        ignored_files=ignored_files,
        manual_case_ids=case_ids,
    )
    return ApiScenarioSourceInspection(
        summary=summary,
        openapi=tuple(inspections),
        manual_cases=tuple(manual_cases),
    )


def validate_manual_case_mapping(
    cases: Any,
    inspection: ApiScenarioSourceInspection,
) -> dict[str, Any]:
    expected = {item.case.case_id for item in inspection.manual_cases}
    known_sources = {(item.source_path, item.case.case_id) for item in inspection.manual_cases}
    mapped: set[str] = set()
    confirmed: set[str] = set()
    unconfirmed: set[str] = set()
    unknown: set[tuple[str, str]] = set()
    for case in cases.cases:
        refs = [
            ref
            for ref in case.source_refs
            if ref.source_type == "manual-test-case" and ref.confidence == "high"
        ]
        for ref in refs:
            key = (ref.source_path, ref.chunk_id)
            if key not in known_sources:
                unknown.add(key)
                continue
            mapped.add(ref.chunk_id)
            if case.contract_status == "confirmed":
                confirmed.add(ref.chunk_id)
            else:
                unconfirmed.add(ref.chunk_id)
    if unknown:
        raise ValueError(f"API cases reference unknown manual test cases: {sorted(unknown)}")
    missing = sorted(expected - mapped)
    if missing:
        raise ValueError(f"API cases do not map all manual test cases: {missing}")
    return {
        "manual_case_total": len(expected),
        "manual_case_confirmed": len(confirmed),
        "manual_case_unconfirmed": len(unconfirmed - confirmed),
        "manual_case_unmapped_ids": missing,
    }


def _parse_yaml_or_json(text: str, *, path: str, suffix: str) -> Any:
    if suffix not in {".yaml", ".yml", ".json"}:
        return None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML/JSON source {path}: {exc}") from exc


def _append_manual_source(
    path: str,
    testcase_set: TestCaseSet,
    files: list[ApiScenarioSourceFile],
    cases: list[ManualTestCaseSource],
) -> None:
    ids = [case.case_id for case in testcase_set.cases]
    files.append(ApiScenarioSourceFile(path=path, kind="manual_test_cases", case_ids=ids))
    cases.extend(ManualTestCaseSource(source_path=path, case=case) for case in testcase_set.cases)


def _parse_csv_testcases(text: str, *, path: str) -> TestCaseSet:
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != TESTCASE_HEADERS:
        raise ValueError(f"CSV source {path} must use the exact ordered 11-column header")
    rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError(f"CSV source {path} has no test cases")
    return _testcase_set_from_rows(rows, path=path)


def _parse_markdown_testcases(text: str, *, path: str) -> TestCaseSet | None:
    lines = text.splitlines()
    header_cells = list(TESTCASE_HEADERS)
    index = next(
        (i for i, line in enumerate(lines) if _split_markdown_row(line) == header_cells),
        None,
    )
    if index is None:
        return None
    if index + 1 >= len(lines) or len(_split_markdown_row(lines[index + 1])) != 11:
        raise ValueError(f"Markdown source {path} has an invalid 11-column delimiter")
    rows: list[dict[str, str]] = []
    for line_number, line in enumerate(lines[index + 2 :], start=index + 3):
        if not line.lstrip().startswith("|"):
            break
        cells = _split_markdown_row(line)
        if len(cells) != 11:
            raise ValueError(
                f"Markdown source {path} row {line_number} has {len(cells)} columns instead of 11"
            )
        rows.append(dict(zip(TESTCASE_HEADERS, cells, strict=True)))
    if not rows:
        raise ValueError(f"Markdown source {path} has no test cases")
    return _testcase_set_from_rows(rows, path=path)


def _testcase_set_from_rows(rows: list[dict[str, str]], *, path: str) -> TestCaseSet:
    cases = [
        TestCase(
            case_id=row[TESTCASE_HEADERS[0]].strip(),
            rule_ids=_split_list(row[TESTCASE_HEADERS[1]]),
            title=row[TESTCASE_HEADERS[2]].strip(),
            test_type=row[TESTCASE_HEADERS[3]].strip(),
            priority=row[TESTCASE_HEADERS[4]].strip(),
            preconditions=_split_values(row[TESTCASE_HEADERS[5]]),
            test_data=_split_values(row[TESTCASE_HEADERS[6]]),
            steps=_split_values(row[TESTCASE_HEADERS[7]]),
            expected_results=_split_values(row[TESTCASE_HEADERS[8]]),
            assertions=_split_values(row[TESTCASE_HEADERS[9]]),
            pending_items=(
                []
                if row[TESTCASE_HEADERS[10]].strip() in {"", "-", "无"}
                else _split_values(row[TESTCASE_HEADERS[10]])
            ),
        )
        for row in rows
    ]
    by_rule: dict[str, list[str]] = defaultdict(list)
    for case in cases:
        for rule_id in case.rule_ids:
            by_rule[rule_id].append(case.case_id)
    coverage = [
        CoverageMapping(
            rule_id=rule_id,
            case_ids=case_ids,
            rationale=f"Imported from manual API test cases in {path}",
        )
        for rule_id, case_ids in by_rule.items()
    ]
    return TestCaseSet(cases=cases, coverage=coverage)


def _split_markdown_row(line: str) -> list[str]:
    value = line.strip()
    if not value.startswith("|") or not value.endswith("|"):
        return []
    return [cell.strip().replace(r"\|", "|") for cell in value[1:-1].split("|")]


def _split_list(value: str) -> list[str]:
    return [item.strip() for item in value.replace("<br>", ",").split(",") if item.strip()]


def _split_values(value: str) -> list[str]:
    normalized = value.replace("<br/>", "<br>").replace("<br />", "<br>")
    values = [item.strip() for item in normalized.split("<br>") if item.strip()]
    return values or ["未提供"]
