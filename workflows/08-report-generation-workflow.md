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

- `prompts/report-generation-prompt.md`
- `rules/status-rules.md`
- `rules/agent-output-rules.md`
- `skills/reporting/qa-report-writing-skill.md`
- `knowledge/templates/qa-report-template.md`
- `scripts/generate_markdown_report.py`

## 输入文件

- `prd/<id>/analysis/`
- `prd/<id>/cases/`
- `prd/<id>/execution/runs/`
- `prd/<id>/defects/`
- `prd/<id>/defects/bug-drafts/`
- `prd/<id>/workspace.yml`

## 输出路径

- `prd/<id>/report/qa-review.md`

说明：`qa-review.md` 是 AI 生成草稿；`qa-report.md` 是人工确认后的正式报告，可后续生成。

## 执行步骤

1. 校验 PRD 工作区结构。
2. 汇总所有可用 QA 产物。
3. 生成报告草稿。
4. 标记未覆盖范围、风险和待确认项。
5. 等待人工确认。

## 前置条件

- PRD 工作区结构校验通过。
- 需求分析、用例、执行结果、失败分析中缺失的部分必须在报告中明确列为未覆盖。
- 报告生成只能输出草稿，不能替代人工结论。
- 报告应采用摘要和产物索引，不得大段拼接上游 Markdown 原文。

## 状态标记

- `qa-review.md` 必须标记为 `needs_human_confirmation`。
- 正式报告 `qa-report.md` 只能在人工确认后生成。

## 异常处理

- 缺少执行结果时，不得伪造通过率，只能写“未执行”。
- 缺少失败日志时，不得生成真实缺陷结论。
- 审核门未通过时，报告必须列出阻塞项。

## 禁止事项

- 不把草稿报告当作正式发布结论。
- 不隐藏未覆盖范围和未解决风险。

## 验收标准

- 报告包含范围、执行概况、缺陷风险和结论草稿。
- 待人工确认项明确。

## 人工审核点

- 报告结论是否可发布。
- 风险是否充分披露。
