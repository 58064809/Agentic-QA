# 02 测试用例生成工作流

## 适用场景

用于基于已审核或待审核的需求分析生成测试用例草稿。

## 触发命令

- “为 `prd/<id>` 生成测试用例。”
- “根据需求分析设计用例。”

## 主 Agent

Testcase Design Agent

## 辅助 Agent

Requirement Analysis Agent 协助解释需求，Failure Analysis Agent 提供历史风险视角。

## 必须读取

- `tasks/02-generate-testcases.md`
- `prompts/testcase-design-prompt.md`
- `rules/testcase-rules.md`
- `rules/review-gate-rules.md`
- `skills/test-design-skill.md`
- `skills/equivalence-partitioning-skill.md`
- `skills/boundary-value-analysis-skill.md`
- `skills/scenario-modeling-skill.md`
- `skills/state-transition-modeling-skill.md`
- `skills/risk-based-testing-skill.md`
- `knowledge/templates/testcase-template.md`

## 输入文件

- `prd/<id>/requirement.md`
- `prd/<id>/api-doc.md`
- `prd/<id>/10-analysis/requirement-analysis.md`
- `prd/<id>/metadata.yml`

## 输出路径

- `prd/<id>/20-testcases/testcases.md`

## 执行步骤

1. 检查需求分析审核状态。
2. 建立需求到用例的覆盖关系。
3. 使用等价类、边界值、场景、状态迁移和风险方法设计用例。
4. 按模板输出用例表。
5. 标记为 `needs_human_review`。

## 前置条件

- 已存在原始需求和需求分析草稿。
- 若需求分析未审核，只能生成待审核用例草稿。
- 必须读取测试用例模板和测试用例规则。

## 状态标记

- 用例文件必须写明 `status: needs_human_review`。
- 必须写明“基于哪些输入材料生成”。
- 不得把用例标记为正式通过。

## 异常处理

- 上游需求分析缺失时，先提示执行需求分析工作流。
- 需求规则不清时，生成待确认问题并避免生成强断言用例。
- 若用例覆盖不足，必须在文件中列出未覆盖范围。

## 禁止事项

- 不生成无法执行或无法判断预期的用例。
- 不忽略异常和边界场景。
- 不把未审核用例作为自动化输入。

## 验收标准

- 用例包含标题、优先级、前置条件、步骤和预期。
- 覆盖正向、异常、边界、状态和高风险场景。

## 人工审核点

- 用例覆盖是否充分。
- 优先级和预期是否合理。
