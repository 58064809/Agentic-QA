# 06 失败分析工作流

## 适用场景

用于分析测试失败、错误日志和异常结果。

## 触发命令

- “分析 `prd/<id>` 的失败原因。”
- “根据执行结果分类失败。”

## 主 Agent

Failure Analysis Agent

## 辅助 Agent

Test Execution Agent 提供执行上下文，Bug Draft Agent 准备缺陷草稿。

## 必须读取

- `tasks/06-analyze-failures.md`
- `prompts/failure-analysis-prompt.md`
- `rules/failure-analysis-rules.md`
- `rules/test-execution-rules.md`
- `skills/failure-log-analysis-skill.md`
- `knowledge/historical-lessons/README.md`

## 输入文件

- `prd/<id>/50-execution-results/`
- `prd/<id>/20-testcases/testcases.md`
- `prd/<id>/requirement.md`
- `prd/<id>/api-doc.md`

## 输出路径

- `prd/<id>/60-failure-analysis/failure-analysis.md`

## 执行步骤

1. 汇总失败日志和失败用例。
2. 按失败分类规则逐项归因。
3. 整理证据、复现条件和不确定点。
4. 标记可能真实缺陷和需要补充信息的项。
5. 输出待人工确认的失败分析。

## 禁止事项

- 不在证据不足时武断定性。
- 不忽略脚本、环境和测试数据问题。

## 验收标准

- 每个失败都有分类和依据。
- 真实缺陷候选有证据链。

## 人工审核点

- 分类是否准确。
- 是否需要补充日志或复现。
