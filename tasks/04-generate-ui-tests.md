# 04 生成 UI 测试

## 任务目标

生成 Playwright UI 自动化脚本草稿。

## 触发命令示例

- “生成 `prd/sample-login-requirement` 的 UI 测试。”

## 输入文件

- `prd/<id>/requirement.md`
- `prd/<id>/20-testcases/testcases.md`
- `prd/<id>/metadata.yml`

## 必须读取的 Agent/Workflow/Prompt/Rules/Skills/Knowledge

- `agents/ui-test-generation-agent.md`
- `workflows/04-ui-test-generation-workflow.md`
- `prompts/ui-test-generation-prompt.md`
- `rules/ui-test-rules.md`
- `skills/playwright-ui-test-skill.md`

## 执行步骤

1. 选择关键用户路径。
2. 设计选择器和测试数据。
3. 生成脚本草稿。
4. 标注需要人工处理的依赖。

## 输出路径

- `prd/<id>/40-ui-tests/generated/`

## 禁止事项

- 不绕过安全机制。

## 验收标准

- 脚本可维护，前提清晰。

## 人工审核点

- UI 场景和执行风险。
