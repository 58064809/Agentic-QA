# Review Gate

候选产物写入后，run 状态必须为 `needs_human_review` 或 `partial` 并停止。Agent、
ModelGateway、Tool 和 MCP 都不能构造人工批准或调用发布工具。

人工 `ReviewDecision` 支持 approve、reject、revise、hold 和 show_diff。多候选的状态变更
必须指定单个 artifact 或 `all`。approve 先记录 `approved`，Artifact Store 再执行原子
promote；成功后记录 `confirmed`。其他状态不能 promote。

`review_assistant` 的 allowlist 只有只读和 diff 工具，没有 `artifact.promote`。
