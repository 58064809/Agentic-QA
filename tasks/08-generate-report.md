# 08 生成报告

## 任务目标

生成 QA 报告草稿。

## 触发命令示例

- “生成 `prd/sample-login-requirement` 的 QA 报告。”

## 输入文件

- `prd/<id>/10-analysis/`
- `prd/<id>/20-testcases/`
- `prd/<id>/50-execution-results/`
- `prd/<id>/60-failure-analysis/`
- `prd/<id>/70-bugs/`
- `prd/<id>/metadata.yml`

## 必须读取的 Agent/Workflow/Prompt/Rules/Skills/Knowledge

- `agents/report-generation-agent.md`
- `workflows/08-report-generation-workflow.md`
- `prompts/report-generation-prompt.md`
- `rules/status-rules.md`
- `rules/codex-output-rules.md`
- `skills/qa-report-writing-skill.md`
- `knowledge/templates/qa-report-template.md`

## 执行步骤

1. 校验工作区。
2. 汇总 QA 产物。
3. 生成报告草稿。
4. 标注风险和待确认项。

## 输出路径

- `prd/<id>/80-reports/qa-report-draft.md`

说明：`qa-report-draft.md` 是 AI 生成草稿；`qa-report.md` 是人工确认后的正式报告，可后续生成。

## 禁止事项

- 不输出未经确认的正式结论。
- 不把完整上游 Markdown 原文大段粘贴进报告。

## 验收标准

- 报告结构完整，风险明确。

## 人工审核点

- 报告结论和发布建议。
