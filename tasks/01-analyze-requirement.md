# 01 分析需求

## 任务目标

生成可审核的需求分析草稿。

## 触发命令示例

- “分析 `prd/sample-login-requirement`。”

## 输入文件

- `prd/<id>/requirement.md`
- `prd/<id>/api-doc.md`
- `prd/<id>/metadata.yml`

## 必须读取的 Agent/Workflow/Prompt/Rules/Skills/Knowledge

- `agents/requirement-analysis-agent.md`
- `workflows/01-requirement-analysis-workflow.md`
- `prompts/requirement-analysis-prompt.md`
- `rules/requirement-analysis-rules.md`
- `skills/requirement-decomposition-skill.md`
- `knowledge/templates/requirement-analysis-template.md`

## 执行步骤

1. 校验工作区。
2. 读取需求和接口文档。
3. 拆解规则、流程、边界、风险和待澄清问题。
4. 生成分析草稿。

## 输出路径

- `prd/<id>/10-analysis/requirement-analysis.md`

## 禁止事项

- 不改写原始需求。

## 验收标准

- 分析内容可追溯，待澄清项清晰。

## 人工审核点

- 分析是否准确完整。
