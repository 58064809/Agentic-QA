# 当前状态规则

Review Gate 的唯一状态机实现在 `runtime/review/state_machine.py`。

| 状态 | 含义 | 允许的下一步 |
|---|---|---|
| `needs_human_review` | 候选产物等待人工审核 | approve / reject / revise / hold / clarify / show_diff |
| `approved` | 审核通过，尚未发布 | deterministic promote |
| `needs_changes` | 要求修订 | 创建修订 run 后重新审核 |
| `rejected` | 当前候选被否决 | 停止或创建新 run |
| `confirmed` | promote 成功，正式产物已写入 | 只能由后续新 run 产生新版本 |

规则：

- 只有 `needs_human_review` 可以执行 approve、reject 或 revise。
- show_diff、hold 和 clarify 不改变审核状态。
- 多产物审核必须指定单个 artifact 或 `all`。
- 只有 `approved` 可以 promote。
- `confirmed` 只能由 promote 成功产生，Review Gate 和 LLM 都不能直接写入。
- 未在表中定义的状态不进入当前审核链路。
