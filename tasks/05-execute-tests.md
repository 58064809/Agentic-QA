# 05 执行测试

## 任务目标

执行已审核测试脚本并收集结果。

## 触发命令示例

- “执行 `prd/sample-login-requirement` 的测试。”

## 输入文件

- `prd/<id>/30-api-tests/generated/`
- `prd/<id>/40-ui-tests/generated/`
- `prd/<id>/metadata.yml`

## 必须读取的 Agent/Workflow/Prompt/Rules/Skills/Knowledge

- `agents/test-execution-agent.md`
- `workflows/05-test-execution-workflow.md`
- `prompts/test-execution-prompt.md`
- `rules/test-execution-rules.md`
- `scripts/run_pytest.py`
- `scripts/collect_test_results.py`

## 执行步骤

1. 检查执行前确认。
2. 运行测试命令。
3. 保存日志和报告。
4. 汇总结果。

## 输出路径

- `prd/<id>/50-execution-results/`

## 禁止事项

- 不在未授权环境执行。

## 验收标准

- 命令和结果可追溯。

## 人工审核点

- 结果是否可信。
