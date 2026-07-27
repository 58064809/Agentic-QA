from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from harness.application.qa_design import parse_testcase_markdown
from harness.application.quality import (
    QualityComponentConfiguration,
    QualityContext,
    QualityIssue,
    StrategyRequirements,
    StrategyResult,
)
from harness.domain.models import StrictModel


class DeclarativeCondition(StrictModel):
    field: str
    operator: Literal["contains", "equals", "present"] = "contains"
    value: str | None = None


class DeclarativeRequiredRule(StrictModel):
    rule_id: str
    condition_mode: Literal["all_of", "any_of"] = "all_of"
    conditions: list[DeclarativeCondition] = Field(default_factory=list)


class DeclarativeBoundary(StrictModel):
    rule_id: str
    field: str
    values: list[str] = Field(min_length=1)


class DeclarativeQualityConfiguration(QualityComponentConfiguration):
    schema_version: Literal["agentic-qa.declarative-quality-policy.v1"] = (
        "agentic-qa.declarative-quality-policy.v1"
    )
    name: str
    version: str
    requires_sources: bool = True
    requires_complete_sources: bool = True
    required_rules: list[DeclarativeRequiredRule] = Field(default_factory=list)
    boundary_requirements: list[DeclarativeBoundary] = Field(default_factory=list)
    forbidden_inventions: list[str] = Field(default_factory=list)


class DeclarativeQualityStrategy:
    def __init__(self, configuration: DeclarativeQualityConfiguration) -> None:
        self.configuration = configuration
        self.name = configuration.name
        self.version = configuration.version
        self.requirements = StrategyRequirements(
            requires_sources=configuration.requires_sources,
            requires_complete_sources=configuration.requires_complete_sources,
        )

    @classmethod
    def from_manifest(cls, path: Path) -> DeclarativeQualityStrategy:
        payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(DeclarativeQualityConfiguration.model_validate(payload))

    def evaluate(self, context: QualityContext, content: str) -> StrategyResult:
        if context.artifact != "testcases":
            return StrategyResult()
        issues: list[QualityIssue] = []
        try:
            testcase_set = parse_testcase_markdown(content)
        except ValueError as exc:
            return StrategyResult(issues=(self._issue("invalid_testcase_set", str(exc)),))
        mapped_rules = {mapping.rule_id for mapping in testcase_set.coverage}
        matched_cases: dict[str, list[Any]] = {}
        for required in self.configuration.required_rules:
            direct_cases = [
                case for case in testcase_set.cases if required.rule_id in case.rule_ids
            ]
            cases = direct_cases or list(testcase_set.cases)
            corpus = " ".join(
                value
                for case in cases
                for value in [
                    case.title,
                    *case.preconditions,
                    *case.test_data,
                    *case.steps,
                    *case.expected_results,
                    *case.assertions,
                ]
            )
            condition_results = [
                self._condition_matches(condition, corpus) for condition in required.conditions
            ]
            conditions_pass = (
                all(condition_results)
                if required.condition_mode == "all_of"
                else any(condition_results)
            )
            if required.rule_id not in mapped_rules and (
                not condition_results or not conditions_pass
            ):
                issues.append(
                    self._issue(
                        "required_rule_uncovered",
                        f"required rule {required.rule_id} has no direct mapping or "
                        "condition-matched generated rule",
                        rule_id=required.rule_id,
                    )
                )
            elif condition_results and not conditions_pass:
                issues.append(
                    self._issue(
                        "required_rule_conditions_uncovered",
                        f"required rule {required.rule_id} does not satisfy "
                        f"{required.condition_mode} conditions",
                        rule_id=required.rule_id,
                    )
                )
            else:
                matched_cases[required.rule_id] = cases
        for boundary in self.configuration.boundary_requirements:
            cases = matched_cases.get(boundary.rule_id) or [
                case for case in testcase_set.cases if boundary.rule_id in case.rule_ids
            ]
            corpus = " ".join(
                value
                for case in cases
                for value in [*case.test_data, *case.steps, *case.expected_results]
            )
            for value in boundary.values:
                if value not in corpus:
                    issues.append(
                        self._issue(
                            "boundary_value_uncovered",
                            f"{boundary.rule_id} boundary {boundary.field}={value} is not covered",
                            rule_id=boundary.rule_id,
                            value=value,
                        )
                    )
        source = context.source_bundle.corpus.casefold()
        for term in self.configuration.forbidden_inventions:
            if term.casefold() in content.casefold() and term.casefold() not in source:
                issues.append(
                    self._issue(
                        "forbidden_invention",
                        f"candidate invents source-undefined detail: {term}",
                        term=term,
                    )
                )
        return StrategyResult(issues=tuple(issues))

    @staticmethod
    def _condition_matches(condition: DeclarativeCondition, corpus: str) -> bool:
        field = condition.field.casefold()
        value = (condition.value or "").casefold()
        folded = corpus.casefold()
        if condition.operator == "present":
            return field in folded
        if condition.operator == "equals":
            return f"{field}={value}" in folded
        return field in folded and value in folded

    def _issue(self, code: str, message: str, **details: str) -> QualityIssue:
        return QualityIssue(
            policy=self.name,
            version=self.version,
            code=code,
            message=message,
            details=details,
        )
