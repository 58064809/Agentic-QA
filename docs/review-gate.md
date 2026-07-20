# Review Gate

质量门通过的候选写入后，LangGraph 必须在 `interrupt()` 停止。预算超限可生成明确标记为
`partial` 的审核材料，但 partial 不允许 approve 或 promote。Agent、
ModelGateway、Tool 和 MCP 都不能构造人工批准或调用发布工具。

人工 `ReviewDecision` 支持 approve、reject、revise、hold 和 show_diff。多候选的状态变更
必须提供非空 `reviewed_by`，并指定单个 artifact 或 `all`。approve 先进行全量预校验，
Artifact Store 再执行可回滚、
幂等 promote；全部成功后才记录 `confirmed`。其他状态不能 promote。

`review_assistant` 的 allowlist 只有只读和 diff 工具，没有 `artifact.promote`。
