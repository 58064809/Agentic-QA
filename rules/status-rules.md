# 状态规则

## 合法状态

| 状态 | 含义 |
|---|---|
| `draft` | AI 或人创建的草稿，尚未进入审核 |
| `needs_human_review` | 需要人工审核内容质量 |
| `approved` | 人工审核通过 |
| `needs_changes` | 需要修改后重新审核 |
| `rejected` | 被拒绝，不允许继续使用 |
| `needs_human_confirmation` | 需要人工确认事实、环境或执行结果 |
| `confirmed` | 人工确认事实成立 |
| `archived` | 已归档 |

## 流转规则

- 草稿产物默认从 `draft` 开始。
- AI 生成的重要产物完成后应进入 `needs_human_review`。
- 测试执行结果、失败归因和报告结论应进入 `needs_human_confirmation`。
- 存在 `needs_human_review` 或 `needs_human_confirmation` 时不得归档。
