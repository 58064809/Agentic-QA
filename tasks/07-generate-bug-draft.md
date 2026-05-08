# 07 生成缺陷草稿

## 任务目标

把真实缺陷候选整理为缺陷报告草稿。

## 触发命令示例

- “为 `prd/sample-login-requirement` 生成 bug 草稿。”

## 输入文件

- `prd/<id>/60-failure-analysis/failure-analysis.md`
- `prd/<id>/50-execution-results/`
- `prd/<id>/requirement.md`

## 必须读取的 Agent/Workflow/Prompt/Rules/Skills/Knowledge

- `agents/bug-draft-agent.md`
- `workflows/07-bug-draft-workflow.md`
- `prompts/bug-draft-prompt.md`
- `skills/bug-report-writing-skill.md`
- `knowledge/templates/bug-template.md`

## 执行步骤

1. 筛选真实缺陷候选。
2. 提取复现步骤和证据。
3. 生成缺陷草稿。
4. 标注待人工确认项。

## 输出路径

- `prd/<id>/70-bugs/`

## 禁止事项

- 不为非产品问题生成缺陷。

## 验收标准

- 草稿可转入缺陷系统。

## 人工审核点

- 缺陷是否成立。
