from __future__ import annotations

from harness.application.quality import (
    QualityComponentConfiguration,
    QualityContext,
    QualityIssue,
    StrategyRequirements,
    StrategyResult,
)

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


class GenericArtifactStrategy:
    name = "generic-artifact-contracts"
    version = "3.0.0"
    requirements = StrategyRequirements()
    configuration = QualityComponentConfiguration()

    def evaluate(self, context: QualityContext, content: str) -> StrategyResult:
        issues: list[QualityIssue] = []
        if not content.strip():
            issues.append(self._issue("empty_artifact", "artifact content cannot be empty"))
        if context.artifact == "testcases":
            header = "| " + " | ".join(TESTCASE_HEADERS) + " |"
            if header not in content:
                issues.append(self._issue("testcase_headers", "测试用例必须使用固定 11 列表头"))
            if "覆盖矩阵" not in content:
                issues.append(self._issue("coverage_matrix", "测试用例必须包含覆盖矩阵"))
        return StrategyResult(issues=tuple(issues))

    def _issue(self, code: str, message: str) -> QualityIssue:
        return QualityIssue(
            policy=self.name,
            version=self.version,
            code=code,
            message=message,
        )
