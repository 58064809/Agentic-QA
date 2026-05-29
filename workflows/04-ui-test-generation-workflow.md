# 04 UI 测试生成工作流

## 适用场景

用于根据需求和用例生成 Playwright UI 自动化脚本草稿。

## 触发命令

- “为 `prd/<id>` 生成 UI 自动化。”
- “生成登录流程的 Playwright 用例。”

## 主 Agent

UI Test Generation Agent

## 辅助 Agent

Testcase Design Agent 协助选择关键场景，Test Execution Agent 协助说明执行环境。

## 必须读取

- `prompts/ui-test-generation-prompt.md`
- `rules/ui-test-rules.md`
- `rules/automation-rules.md`
- `skills/playwright-ui-test-skill.md`
- `skills/scenario-modeling-skill.md`
- `knowledge/project-rules/assertion-rules.md`
- `knowledge/project-rules/automation-coding-rules.md`

## 输入文件

- `prd/<id>/requirement.md`
- `prd/<id>/20-testcases/testcases.md`
- `prd/<id>/metadata.yml`

## 输出路径

- `prd/<id>/40-ui-tests/generated/`

## 执行步骤

1. 选择适合 UI 自动化的关键路径。
2. 设计稳定选择器策略和数据准备方式。
3. 生成 Playwright 脚本草稿。
4. 标记不可自动化或需要人工处理的步骤。
5. 进入人工审核。

## 前置条件

- 已有可执行的测试用例草稿。
- 页面入口、账号、测试环境和选择器策略已知，或明确列为待确认。
- 涉及验证码、短信、风控时必须先确认替代策略。

## 状态标记

- UI 脚本草稿标记为 `needs_human_review`。
- 执行环境未确认时，不得进入测试执行状态。

## 异常处理

- 页面入口缺失时，只输出测试设计建议，不生成可执行脚本。
- 选择器不稳定时，优先建议补充 test id。
- 第三方跳转不可控时，列出 mock 或人工验证方案。

## 禁止事项

- 不依赖脆弱样式选择器。
- 不绕过验证码、风控或安全机制。
- 不默认对生产环境执行。

## 验收标准

- 脚本结构清晰，选择器策略可维护。
- 明确环境和数据前提。

## 人工审核点

- UI 场景是否适合自动化。
- 执行风险是否可接受。
