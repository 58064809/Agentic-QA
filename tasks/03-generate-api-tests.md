# 03 生成 API 测试

## 任务目标

生成 pytest API 自动化脚本草稿。

## 触发命令示例

- “生成 `prd/sample-login-requirement` 的 API 测试。”

## 输入文件

- `prd/<id>/api-doc.md`
- `prd/<id>/20-testcases/testcases.md`
- `prd/<id>/metadata.yml`

## 必须读取的 Agent/Workflow/Prompt/Rules/Skills/Knowledge

- `agents/api-test-generation-agent.md`
- `workflows/03-api-test-generation-workflow.md`
- `prompts/api-test-generation-prompt.md`
- `rules/api-test-rules.md`
- `skills/api-contract-analysis-skill.md`
- `skills/pytest-api-test-skill.md`

## 执行步骤

1. 检查用例审核状态。
2. 分析接口契约。
3. 生成测试脚本、夹具和数据说明。
4. 标注环境变量和执行方式。

## 输出路径

- `prd/<id>/30-api-tests/generated/`

## 禁止事项

- 不硬编码真实凭据。

## 验收标准

- 脚本可审查，断言明确。

## 人工审核点

- 接口契约、数据和执行风险。
