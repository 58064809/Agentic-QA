from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuntimeWorkflowDefinition:
    workflow_id: str
    task_type: str
    context_files: tuple[str, ...] = field(default_factory=tuple)


BASE_CONTEXT_FILES = (
    "AGENTS.md",
    "COMMANDS.md",
    "docs/roadmap.md",
    "skills/registry/skills.yaml",
    "skills/core/requirement-understanding-skill.md",
    "skills/core/context-building-skill.md",
    "skills/core/rag-retrieval-skill.md",
    "skills/analysis/test-scope-decomposition-skill.md",
    "skills/analysis/risk-identification-skill.md",
    "skills/core/output-formatting-skill.md",
)
ANALYSIS_CONTEXT_FILES = (
    *BASE_CONTEXT_FILES,
    "workflows/01-requirement-analysis-workflow.md",
    "prompts/requirement-analysis-prompt.md",
    "rules/requirement-analysis-rules.md",
    "rules/review-gate-rules.md",
    "rules/artifact-path-rules.md",
    "skills/analysis/requirement-decomposition-skill.md",
    "skills/analysis/business-rule-extraction-skill.md",
    "knowledge/templates/requirement-analysis-template.md",
)
TESTCASE_CONTEXT_FILES = (
    *BASE_CONTEXT_FILES,
    "skills/test-design/test-method-selection-skill.md",
    "skills/test-design/testcase-generation-skill.md",
    "skills/test-design/testcase-review-skill.md",
    "workflows/10-runtime-testcase-generation-workflow.md",
    "workflows/02-testcase-generation-workflow.md",
    "prompts/testcase-design-prompt.md",
    "rules/testcase-rules.md",
    "rules/review-gate-rules.md",
    "rules/artifact-path-rules.md",
    "skills/test-design/test-design-skill.md",
    "skills/test-design/equivalence-partitioning-skill.md",
    "skills/test-design/boundary-value-analysis-skill.md",
    "skills/test-design/scenario-modeling-skill.md",
    "skills/test-design/state-transition-modeling-skill.md",
    "skills/test-design/risk-based-testing-skill.md",
    "knowledge/templates/testcase-template.md",
)
API_TEST_CONTEXT_FILES = (
    *BASE_CONTEXT_FILES,
    "docs/api-test-generation.md",
    "workflows/runtime/api-test-draft.workflow.yml",
    "prompts/api-test-generation.md",
    "skills/api-testing.md",
    "rules/review-gate-rules.md",
    "rules/artifact-path-rules.md",
)


class WorkflowRegistry:
    def __init__(self, definitions: list[RuntimeWorkflowDefinition]) -> None:
        self._by_task_type = {definition.task_type: definition for definition in definitions}
        self._by_workflow_id = {definition.workflow_id: definition for definition in definitions}

    def workflow_id_for_task_type(self, task_type: str | None) -> str:
        try:
            return self._by_task_type[str(task_type)].workflow_id
        except KeyError as exc:
            raise ValueError(f"无法根据 task_type 选择 Workflow DSL: {task_type}") from exc

    def definition_for_task_type(self, task_type: str | None) -> RuntimeWorkflowDefinition:
        try:
            return self._by_task_type[str(task_type)]
        except KeyError as exc:
            raise ValueError(f"未知 workflow task_type: {task_type}") from exc

    def definition_for_workflow_id(self, workflow_id: str) -> RuntimeWorkflowDefinition:
        try:
            return self._by_workflow_id[workflow_id]
        except KeyError as exc:
            raise ValueError(f"未知 workflow_id: {workflow_id}") from exc

    def registered_task_types(self) -> set[str]:
        return set(self._by_task_type)

    def registered_workflow_ids(self) -> set[str]:
        return set(self._by_workflow_id)


DEFAULT_WORKFLOW_REGISTRY = WorkflowRegistry(
    [
        RuntimeWorkflowDefinition(
            workflow_id="requirement_analysis",
            task_type="analysis",
            context_files=ANALYSIS_CONTEXT_FILES,
        ),
        RuntimeWorkflowDefinition(
            workflow_id="testcase_generation",
            task_type="testcase_generation",
            context_files=TESTCASE_CONTEXT_FILES,
        ),
        RuntimeWorkflowDefinition(
            workflow_id="api_test_draft",
            task_type="api_test_draft",
            context_files=API_TEST_CONTEXT_FILES,
        ),
        RuntimeWorkflowDefinition(
            workflow_id="analysis_and_testcases",
            task_type="mvp_analysis_testcases",
            context_files=tuple(sorted({*ANALYSIS_CONTEXT_FILES, *TESTCASE_CONTEXT_FILES})),
        ),
    ]
)
