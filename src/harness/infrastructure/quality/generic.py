from __future__ import annotations

import re

import yaml
from pydantic import ValidationError

from harness.application.api_contract_validation import validate_api_contracts
from harness.application.qa_design import parse_testcase_markdown
from harness.application.quality import (
    QualityComponentConfiguration,
    QualityContext,
    QualityIssue,
    StrategyRequirements,
    StrategyResult,
)
from harness.application.source import SourceCompleteness
from harness.domain.schemas.api_test_cases import (
    ApiTestCasesDraft,
    validate_api_case_runtime_definitions,
    validate_api_cleanup_policy,
)
from harness.domain.security import contains_likely_secret
from harness.infrastructure.api_scenario_sources import (
    inspect_api_scenario_sources,
    validate_manual_case_mapping,
)
from harness.infrastructure.tools.openapi import inspect_openapi

PLACEHOLDER_MAPPING = re.compile(r"(?:暂无|未覆盖|待补充|后续设计|TODO|TBD)", re.IGNORECASE)
UNSUPPORTED_IMPLEMENTATION = re.compile(
    r"(?P<term>[\w\u4e00-\u9fff]{1,24}(?P<marker>页面|按钮|接口|数据库表|数据表|字段|日志))"
)
REQUIRED_REQUIREMENT_SECTIONS = (
    "## 来源清单",
    "## 参与者",
    "## 业务对象",
    "## 业务流程",
    "## 规则目录",
    "## 边界与状态迁移",
    "## 冲突与歧义",
    "## 待确认项",
    "## 测试影响",
)


def _implementation_term_supported(term: str, marker: str, source_corpus: str) -> bool:
    normalized = term.casefold()
    if normalized in source_corpus:
        return True
    stem = normalized[: -len(marker)]
    normalized_marker = marker.casefold()
    for stem_length in range(min(len(stem), 8), 1, -1):
        if f"{stem[-stem_length:]}{normalized_marker}" in source_corpus:
            return True
    return False


class GenericArtifactStrategy:
    name = "generic-artifact-contracts"
    version = "4.6.0"
    requirements = StrategyRequirements()
    configuration = QualityComponentConfiguration()

    def evaluate(self, context: QualityContext, content: str) -> StrategyResult:
        issues: list[QualityIssue] = []
        if not content.strip():
            return StrategyResult(
                issues=(self._issue("empty_artifact", "artifact content cannot be empty"),)
            )
        metrics: dict[str, object] = {}
        if context.artifact == "testcases":
            issues.extend(self._testcase_issues(context, content))
        elif context.artifact == "requirement_analysis":
            issues.extend(self._requirement_issues(content))
        elif context.artifact == "api_test_draft":
            api_issues, metrics = self._api_test_issues(context, content)
            issues.extend(api_issues)
        elif context.artifact == "api_discovery_report":
            issues.extend(self._api_discovery_issues(content))
        return StrategyResult(issues=tuple(issues), metrics=metrics)

    def _testcase_issues(
        self,
        context: QualityContext,
        content: str,
    ) -> list[QualityIssue]:
        try:
            testcase_set = parse_testcase_markdown(content)
        except (ValueError, ValidationError) as exc:
            return [
                self._issue(
                    "invalid_testcase_set",
                    f"testcases must be a valid deterministic 11-column TestCaseSet: {exc}",
                )
            ]

        issues: list[QualityIssue] = []
        for mapping in testcase_set.coverage:
            if PLACEHOLDER_MAPPING.search(mapping.rationale):
                issues.append(
                    self._issue(
                        "placeholder_coverage",
                        "coverage matrix cannot contain placeholder mappings",
                        rule_id=mapping.rule_id,
                    )
                )

        source_corpus = context.source_bundle.corpus.casefold()
        for case in testcase_set.cases:
            if len(case.rule_ids) > 1 and any(
                conjunction in case.title
                for conjunction in ("以及", "并且", "同时验证", "全部规则")
            ):
                issues.append(
                    self._issue(
                        "non_atomic_testcase",
                        f"{case.case_id} combines independent rules in one test objective",
                        case_id=case.case_id,
                    )
                )
            case_text = " ".join(
                [
                    case.title,
                    *case.preconditions,
                    *case.test_data,
                    *case.steps,
                    *case.expected_results,
                    *case.assertions,
                ]
            )
            pending_text = " ".join(case.pending_items)
            for match in UNSUPPORTED_IMPLEMENTATION.finditer(case_text):
                term = match.group("term")
                marker = match.group("marker")
                if (
                    source_corpus
                    and not _implementation_term_supported(term, marker, source_corpus)
                    and term not in pending_text
                ):
                    issues.append(
                        self._issue(
                            "unsupported_implementation_detail",
                            f"{case.case_id} uses a page/API/field detail absent from "
                            f"frozen sources: {term}",
                            case_id=case.case_id,
                            term=term,
                        )
                    )
        return issues

    def _api_test_issues(
        self,
        context: QualityContext,
        content: str,
    ) -> tuple[list[QualityIssue], dict[str, object]]:
        try:
            payload = yaml.safe_load(content)
            draft = ApiTestCasesDraft.model_validate(payload)
        except (yaml.YAMLError, ValidationError) as exc:
            return (
                [
                    self._issue(
                        "invalid_api_test_draft",
                        f"api_test_draft must satisfy agentic-qa.api-cases.v1.1: {exc}",
                    )
                ],
                {},
            )
        issues: list[QualityIssue] = []
        frozen_sources = {document.path for document in context.source_bundle.documents}
        try:
            validate_api_case_runtime_definitions(draft.cases)
        except ValueError as exc:
            assertion_error = "assertions[" in str(exc)
            issues.append(
                self._issue(
                    "invalid_api_assertion"
                    if assertion_error
                    else "invalid_api_runtime_definition",
                    (
                        f"api_test_draft has invalid API assertions: {exc}"
                        if assertion_error
                        else f"api_test_draft has invalid variables or cleanup: {exc}"
                    ),
                )
            )
        try:
            validate_api_cleanup_policy(
                draft.cases,
                context.cleanup_exempt_operations,
                context.operation_policies,
            )
        except ValueError as exc:
            issues.append(
                self._issue(
                    "api_cleanup_required",
                    str(exc),
                )
            )
        for case in draft.cases:
            if case.contract_status != "confirmed":
                continue
            referenced_sources = {
                reference.source_path
                for reference in case.source_refs
                if reference.source_type == "openapi" and reference.confidence == "high"
            }
            if not referenced_sources & frozen_sources:
                issues.append(
                    self._issue(
                        "confirmed_api_without_frozen_contract",
                        f"{case.id} has no high-confidence OpenAPI reference in the "
                        "frozen SourceBundle",
                        case_id=case.id,
                    )
                )
        referenced_openapi = {
            reference.source_path
            for case in draft.cases
            for reference in case.source_refs
            if case.contract_status == "confirmed"
            and reference.source_type == "openapi"
            and reference.confidence == "high"
        }
        inspections = []
        for document in context.source_bundle.documents:
            source_text = context.full_source_texts.get(document.path, document.text)
            if (
                document.path not in referenced_openapi
                or (
                    document.completeness != SourceCompleteness.COMPLETE
                    and document.path not in context.full_source_texts
                )
                or source_text is None
            ):
                continue
            try:
                inspections.append(
                    inspect_openapi(yaml.safe_load(source_text), source=document.path)
                )
            except (TypeError, ValueError, yaml.YAMLError) as exc:
                issues.append(
                    self._issue(
                        "openapi_contract_unavailable",
                        f"{document.path} cannot be used for deterministic API validation: {exc}",
                        source_path=document.path,
                    )
                )
        if inspections:
            result = validate_api_contracts(draft, inspections)
            issues.extend(
                self._issue(
                    f"api_contract_{issue.code}",
                    issue.message,
                    case_id=issue.case_id,
                    instance_id=issue.instance_id,
                    location=issue.location,
                )
                for issue in result.issues
            )
        metrics: dict[str, object] = {}
        try:
            scenario_sources = inspect_api_scenario_sources(
                context.source_bundle,
                require_complete=False,
                full_text_loader=(
                    context.full_source_texts.__getitem__ if context.full_source_texts else None
                ),
            )
            if scenario_sources.manual_cases:
                metrics = validate_manual_case_mapping(draft, scenario_sources)
        except (TypeError, ValueError, yaml.YAMLError) as exc:
            issues.append(
                self._issue(
                    "invalid_manual_test_case_mapping",
                    f"api_test_draft must map every frozen manual test case: {exc}",
                )
            )
        return issues, metrics

    def _api_discovery_issues(self, content: str) -> list[QualityIssue]:
        required_sections = (
            "## 采集来源",
            "## 接口调用链",
            "## 业务接口候选清单",
            "## 请求与响应结构摘要",
            "## 与 OpenAPI 契约的关系",
            "## 脱敏说明",
            "## 待确认问题",
        )
        missing = [section for section in required_sections if section not in content]
        issues: list[QualityIssue] = []
        if missing:
            issues.append(
                self._issue(
                    "api_discovery_sections",
                    f"API discovery report misses deterministic sections: {missing}",
                )
            )
        if "不代表完整 API 契约" not in content:
            issues.append(
                self._issue(
                    "api_discovery_contract_claim",
                    "API discovery report must state that observed traffic is not a "
                    "complete API contract",
                )
            )
        if contains_likely_secret(content):
            issues.append(
                self._issue(
                    "api_discovery_secret",
                    "API discovery report contains a likely unredacted secret",
                )
            )
        return issues

    def _requirement_issues(self, content: str) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        missing = [section for section in REQUIRED_REQUIREMENT_SECTIONS if section not in content]
        if missing:
            issues.append(
                self._issue(
                    "requirement_sections",
                    f"requirement analysis misses deterministic sections: {missing}",
                )
            )
        confirmed_rows = [
            line
            for line in content.splitlines()
            if line.startswith("| ") and " | confirmed | " in line
        ]
        for row in confirmed_rows:
            columns = [item.strip() for item in row.strip("|").split("|")]
            if len(columns) != 6 or not columns[-1] or columns[-1] == "待确认":
                issues.append(
                    self._issue(
                        "confirmed_rule_without_source",
                        "confirmed requirement rules must include a traceable source",
                    )
                )
                break
        return issues

    def _issue(self, code: str, message: str, **details: str) -> QualityIssue:
        return QualityIssue(
            policy=self.name,
            version=self.version,
            code=code,
            message=message,
            details=details,
        )
