# 06 分析失败

## 任务目标

对测试失败进行分类和证据整理。

## 触发命令示例

- “分析 `prd/sample-login-requirement` 的失败原因。”

## 输入文件

- `prd/<id>/50-execution-results/`
- `prd/<id>/20-testcases/testcases.md`
- `prd/<id>/requirement.md`
- `prd/<id>/api-doc.md`

## 必须读取的 Agent/Workflow/Prompt/Rules/Skills/Knowledge

- `agents/failure-analysis-agent.md`
- `workflows/06-failure-analysis-workflow.md`
- `prompts/failure-analysis-prompt.md`
- `rules/failure-analysis-rules.md`
- `skills/failure-log-analysis-skill.md`

## 执行步骤

1. 汇总失败。
2. 按分类规则归因。
3. 记录证据和待确认项。
4. 输出失败分析。

## 输出路径

- `prd/<id>/60-failure-analysis/failure-analysis.md`

## 禁止事项

- 不武断定性。

## 验收标准

- 每个失败有分类和依据。

## 人工审核点

- 失败分类和证据是否成立。
