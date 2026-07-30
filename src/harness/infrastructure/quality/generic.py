from __future__ import annotations

import re

from pydantic import ValidationError

from harness.application.qa_design import parse_testcase_markdown
from harness.application.quality import (
    QualityComponentConfiguration,
    QualityContext,
    QualityIssue,
    StrategyRequirements,
    StrategyResult,
)

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
    version = "4.1.0"
    requirements = StrategyRequirements()
    configuration = QualityComponentConfiguration()

    def evaluate(self, context: QualityContext, content: str) -> StrategyResult:
        issues: list[QualityIssue] = []
        if not content.strip():
            return StrategyResult(
                issues=(self._issue("empty_artifact", "artifact content cannot be empty"),)
            )
        if context.artifact == "testcases":
            issues.extend(self._testcase_issues(context, content))
        elif context.artifact == "requirement_analysis":
            issues.extend(self._requirement_issues(content))
        return StrategyResult(issues=tuple(issues))

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
