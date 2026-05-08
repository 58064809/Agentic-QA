# 08 报告生成工作流

## 适用场景

用于汇总需求分析、测试用例、执行结果、失败分析和缺陷，生成 QA 报告草稿。

## 触发命令

- “生成 `prd/<id>` 的 QA 报告。”
- “汇总测试结果并输出报告草稿。”

## 主 Agent

Report Generation Agent

## 辅助 Agent

Test Execution Agent、Failure Analysis Agent、Bug Draft Agent 提供输入说明。

## 必须读取

- `tasks/08-generate-report.md`
- `prompts/report-generation-prompt.md`
- `rules/status-rules.md`
- `skills/qa-report-writing-skill.md`
- `knowledge/templates/qa-report-template.md`
- `scripts/generate_markdown_report.py`

## 输入文件

- `prd/<id>/10-analysis/`
- `prd/<id>/20-testcases/`
- `prd/<id>/50-execution-results/`
- `prd/<id>/60-failure-analysis/`
- `prd/<id>/70-bugs/`
- `prd/<id>/metadata.yml`

## 输出路径

- `prd/<id>/80-reports/qa-report-draft.md`

## 执行步骤

1. 校验 PRD 工作区结构。
2. 汇总所有可用 QA 产物。
3. 生成报告草稿。
4. 标记未覆盖范围、风险和待确认项。
5. 等待人工确认。

## 禁止事项

- 不把草稿报告当作正式发布结论。
- 不隐藏未覆盖范围和未解决风险。

## 验收标准

- 报告包含范围、执行概况、缺陷风险和结论草稿。
- 待人工确认项明确。

## 人工审核点

- 报告结论是否可发布。
- 风险是否充分披露。
