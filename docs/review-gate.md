# Review Gate

质量门通过后，候选先写入 `candidates/<run_id>/`，LangGraph 再通过 `interrupt()` 暂停。
Agent、模型、Tool、MCP 和 `review_assistant` 均不能构造人工批准或直接发布。

`resume_run(ResumeRunCommand)` 只处理崩溃恢复，不接受审核决定。`review_run(ReviewRunCommand)`
只处理人工 `ReviewDecision`。多候选的 approve、reject 或 revise 必须指定单个 artifact 或
`all`，并提供非空 `reviewed_by` 与原因。

partial 候选不能 approve 或 promote。approve 会先全量预校验，再执行可回滚、幂等的
deterministic promote；只有全部复制和历史索引更新成功后才将审核状态写为 `confirmed`，
全部候选 confirmed 后 run 才进入 `published`。reject 和 revise 不发布，修订必须创建新 run，
不能覆盖原候选。

`review_assistant` 只能准备摘要和 diff，其 Tool allowlist 不包含 `artifact.promote`。
