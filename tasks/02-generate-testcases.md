# 02 生成测试用例

## 任务目标

基于需求和分析生成测试用例草稿。

## 触发命令示例

- “为 `prd/sample-login-requirement` 生成测试用例。”

## 输入文件

- `prd/<id>/requirement.md`
- `prd/<id>/api-doc.md`
- `prd/<id>/10-analysis/requirement-analysis.md`
- `prd/<id>/metadata.yml`

## 必须读取的 Agent/Workflow/Prompt/Rules/Skills/Knowledge

- `agents/testcase-design-agent.md`
- `workflows/02-testcase-generation-workflow.md`
- `prompts/testcase-design-prompt.md`
- `rules/testcase-rules.md`
- `skills/test-design-skill.md`
- `knowledge/templates/testcase-template.md`

## 执行步骤

1. 检查需求分析审核状态。
2. 建立覆盖矩阵。
3. 设计正向、异常、边界、状态、风险用例。
4. 使用指定表格模板输出。

## 输出路径

- `prd/<id>/20-testcases/testcases.md`

## 禁止事项

- 不生成没有预期结果的用例。

## 验收标准

- 用例字段完整，覆盖关键规则。

## 人工审核点

- 覆盖率和优先级。
