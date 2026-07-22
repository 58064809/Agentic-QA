# Review Gate

Candidate bundle 完整提交后，LangGraph 通过 `interrupt()` 暂停。Agent、模型、Tool、MCP 和
review assistant 都不能构造人工批准或直接发布。

`resume_run` 只处理 planning、running 或 recoverable 的崩溃恢复；`review_run` 只处理人工
ReviewDecision。多候选必须指定单个 artifact 或 `all`。

Approve 必须提交强类型 `ArtifactVersionRef`，其中包含 artifact、`raw|normalized` variant、内容
SHA-256、assessment key 和质量报告 SHA-256。每个目标恰好选择一个版本；存在 normalized 时仍由
审核人显式选择，系统不替用户决定。remediation patch 不是 ArtifactVariant，不能被批准或发布。

Review 服务重新读取质量报告并派生所选版本 verdict。以下情况拒绝 approve：

- Candidate 为 partial；
- 所选版本不存在或存在 blocker；
- Candidate 缺少 manifest、assessment key 或质量报告；
- 内容、报告或引用哈希不一致。

校验通过后，Review 服务生成 `ApprovedArtifactVersion`。Promote 只接受这一强类型对象，并再次
核对文件、报告、assessment key 和 hashes，再确定性复制到 published/history。只有 promote 全部
成功后审核状态才写为 confirmed；所有 Candidate confirmed 后 run 才进入 published。失败的审核
不会把 run 改成 recoverable，也不会留下 approved 假状态。

Reject 和 revise 不发布；修订必须创建新 run，不能覆盖原 Candidate。
