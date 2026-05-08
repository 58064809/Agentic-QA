# 09 归档需求

## 任务目标

在审核通过后生成归档索引。

## 触发命令示例

- “归档 `prd/sample-login-requirement`。”

## 输入文件

- `prd/<id>/metadata.yml`
- `prd/<id>/80-reports/qa-report.md`，人工确认后的正式报告。
- `prd/<id>/80-reports/qa-report-draft.md`，如正式报告尚未生成，则必须作为待确认草稿处理。
- 所有关联产物。

## 必须读取的 Agent/Workflow/Prompt/Rules/Skills/Knowledge

- `agents/archive-agent.md`
- `workflows/09-archive-workflow.md`
- `prompts/archive-prompt.md`
- `rules/archive-rules.md`
- `rules/status-rules.md`
- `scripts/archive_requirement.py`

## 执行步骤

1. 校验工作区结构。
2. 检查阻塞状态。
3. 运行归档脚本。
4. 生成归档索引。

## 输出路径

- `prd/<id>/90-archive/archive-index.md`

## 禁止事项

- 不绕过人工审核状态。

## 验收标准

- 归档索引生成，metadata 状态合法。

## 人工审核点

- 是否允许归档。
