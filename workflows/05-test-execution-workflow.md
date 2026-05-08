# 05 测试执行工作流

## 适用场景

用于运行已审核测试脚本并收集结果。

## 触发命令

- “执行 `prd/<id>` 的测试。”
- “跑 API 测试并收集结果。”

## 主 Agent

Test Execution Agent

## 辅助 Agent

API Test Generation Agent 和 UI Test Generation Agent 协助解释脚本，Failure Analysis Agent 准备后续分析。

## 必须读取

- `tasks/05-execute-tests.md`
- `prompts/test-execution-prompt.md`
- `rules/test-execution-rules.md`
- `rules/automation-rules.md`
- `scripts/run_pytest.py`
- `scripts/collect_test_results.py`

## 输入文件

- `prd/<id>/30-api-tests/generated/`
- `prd/<id>/40-ui-tests/generated/`
- `prd/<id>/metadata.yml`

## 输出路径

- `prd/<id>/50-execution-results/`

## 执行步骤

1. 检查执行前确认状态。
2. 确认环境、账号、数据和风险。
3. 执行测试命令并记录命令。
4. 保存日志、报告和结果摘要。
5. 标记结果为 `needs_human_confirmation`。

## 禁止事项

- 不在未授权环境执行。
- 不隐瞒失败或跳过结果收集。
- 不把失败直接等同于产品缺陷。

## 验收标准

- 有可追溯执行命令和结果文件。
- 失败项可进入后续分析。

## 人工审核点

- 执行环境是否正确。
- 结果是否可信。
