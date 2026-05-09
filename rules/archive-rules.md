# 归档规则

- 归档前必须完成需求分析、用例、执行结果、失败分析和报告的人工审核或确认。
- metadata 中不得存在 `needs_human_review` 或 `needs_human_confirmation`。
- 归档索引必须列出关键产物路径、归档时间和归档状态。
- 归档不代表删除原始材料，不允许清空工作区。
- 归档后如需修改，应创建新的修订记录或新需求工作区。

## 归档前置条件

- `metadata.yml` 结构校验通过。
- 需求分析、测试用例、执行结果、失败分析、QA 报告均已有产物或明确说明不适用。
- `qa-report.md` 已由人工确认生成；若只有 `qa-report-draft.md`，不得作为正式归档结论。
- 所有 review gate 不得处于 `needs_human_review`、`needs_human_confirmation`、`needs_changes` 或 `rejected`。
- 归档脚本失败时，不允许手工伪造 `archive-index.md`。
