# 00 定位需求

## 任务目标

根据用户自然语言命令定位目标 PRD 工作区。

## 触发命令示例

- “找到登录需求。”
- “定位 `sample-login-requirement`。”

## 输入文件

- `prd/_registry.yml`
- 用户命令中提到的路径或关键词。

## 必须读取的 Agent/Workflow/Prompt/Rules/Skills/Knowledge

- `COMMANDS.md`
- `rules/naming-rules.md`
- `rules/artifact-path-rules.md`

## 执行步骤

1. 解析用户命令中的需求 ID、路径或标题关键词。
2. 查询 `prd/_registry.yml`。
3. 若只有一个候选，确认目标工作区。
4. 若有多个候选，向用户列出并请求选择。

## 输出路径

本任务通常不写文件。

## 禁止事项

- 不凭空创建需求，除非用户明确要求新增。

## 验收标准

- 明确目标 PRD 工作区路径。

## 人工审核点

- 目标需求是否选对。
