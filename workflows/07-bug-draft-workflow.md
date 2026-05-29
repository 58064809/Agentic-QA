# 07 缺陷草稿工作流

## 适用场景

用于把已确认或待确认的真实缺陷候选整理为 bug 草稿。

## 触发命令

- “为 `prd/<id>` 生成 bug 草稿。”
- “把真实缺陷整理成缺陷报告。”

## 主 Agent

Bug Draft Agent

## 辅助 Agent

Failure Analysis Agent 提供证据，Requirement Analysis Agent 提供需求依据。

## 必须读取

- `prompts/bug-draft-prompt.md`
- `rules/failure-analysis-rules.md`
- `skills/bug-report-writing-skill.md`
- `knowledge/templates/bug-template.md`

## 输入文件

- `prd/<id>/60-failure-analysis/failure-analysis.md`
- `prd/<id>/50-execution-results/`
- `prd/<id>/requirement.md`

## 输出路径

- `prd/<id>/70-bugs/`

## 执行步骤

1. 选取分类为真实缺陷或待确认真实缺陷的项。
2. 提取复现步骤、实际结果、预期结果和证据。
3. 生成 bug Markdown 草稿。
4. 标记待人工确认项。

## 前置条件

- 已存在失败分析产物。
- 至少有一个真实缺陷候选或用户明确要求生成示例缺陷模板。
- 预期结果可追溯到需求、用例或接口文档。

## 状态标记

- 缺陷草稿标记为 `needs_human_review`。
- 缺陷是否成立必须等待人工确认。

## 异常处理

- 如果失败分类不是“真实缺陷”或“暂无法判断”，不得生成产品缺陷。
- 证据不足时生成待补证据清单，不生成正式缺陷结论。

## 禁止事项

- 不为脚本问题或环境问题生成产品缺陷。
- 不夸大严重程度。
- 不省略复现条件。

## 验收标准

- 缺陷草稿可直接转入缺陷系统。
- 每个结论都有证据。

## 人工审核点

- 是否确认为产品缺陷。
- 严重程度和优先级是否合理。
