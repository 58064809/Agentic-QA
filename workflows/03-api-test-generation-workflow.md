# 03 API 测试生成工作流

## 适用场景

用于把已审核测试用例转换为 pytest API 自动化脚本草稿。

## 触发命令

- “为 `prd/<id>` 生成 API 测试。”
- “根据接口文档生成 pytest 脚本。”

## 主 Agent

API Test Generation Agent

## 辅助 Agent

Testcase Design Agent 提供用例解释，Test Execution Agent 提供执行约束。

## 必须读取

- `prompts/api-test-generation-prompt.md`
- `rules/api-test-rules.md`
- `rules/automation-rules.md`
- `skills/api-contract-analysis-skill.md`
- `skills/pytest-api-test-skill.md`
- `knowledge/project-rules/assertion-rules.md`
- `knowledge/project-rules/automation-coding-rules.md`

## 输入文件

- `prd/<id>/api-doc.md`
- `prd/<id>/20-testcases/testcases.md`
- `prd/<id>/metadata.yml`

## 输出路径

- `prd/<id>/30-api-tests/generated/`

## 执行步骤

1. 检查测试用例审核状态。
2. 提取接口契约、请求参数、响应结构和错误码。
3. 生成 pytest 脚本、测试数据说明和执行说明。
4. 避免硬编码敏感数据。
5. 标记脚本为待人工审核。

## 前置条件

- `api-doc.md` 和 `20-testcases/testcases.md` 已存在。
- 测试用例未审核时，只能输出自动化草稿和待确认项。
- 目标环境、账号、数据不得默认使用生产配置。

## 状态标记

- API 测试计划和脚本必须标记为 `needs_human_review`。
- 脚本必须包含无环境变量时的 skip 保护。
- 不得声明脚本已可直接用于生产验证。

## 异常处理

- API 文档缺少字段、错误码或鉴权方式时，写入测试计划的待确认项。
- 如果接口契约与需求冲突，停止生成强断言并提示人工确认。
- 如果存在破坏性操作，必须写明数据清理和风险。

## 禁止事项

- 不连接生产环境。
- 不提交真实账号、密码、token。
- 不生成无法解释断言依据的脚本。

## 验收标准

- 脚本可读且可独立审查。
- 断言覆盖状态码、业务码和关键字段。

## 人工审核点

- 脚本是否符合接口真实契约。
- 执行环境和测试数据是否允许使用。
