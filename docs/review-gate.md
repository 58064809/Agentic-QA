# Review Gate

Agent、模型、Tool、MCP 和 review assistant 都不能构造人工批准或直接发布。

## ReviewIntent

| Intent | 版本选择 | Candidate | Run/审核投影 | 发布 |
|---|---|---|---|---|
| `approve` | 每个目标一个 raw/normalized | 不修改 | promote 成功后 confirmed/published | 是 |
| `hold` | 不允许 | 不修改 | `on_hold`，写记录与事件 | 否 |
| `reject` | 不允许 | 不修改 | `rejected` | 否 |
| `revise` | 不允许；必须有 revision request | 不覆盖 | `needs_revision` | 否，新 run 修订 |

多 Candidate 必须指定单个 artifact 或 `all`。`show_diff` 不是 ReviewIntent；差异查询不写 Review
Record，也不修改 Run。

## 状态迁移

| 当前状态 | 操作 | 允许结果 |
|---|---|---|
| planning/running/recoverable | `resume_run` | running、needs_human_review、partial、failed |
| needs_human_review/on_hold/partial | `review_run hold` | on_hold |
| needs_human_review/on_hold/partial | reject/revise | rejected/needs_revision |
| needs_human_review/on_hold | approve | 部分 confirmed 或全部 published |
| partial | approve | 拒绝 |
| published/rejected/needs_revision/failed | resume/review | 拒绝不适用操作 |

## Approve 门禁

| 校验位置 | 必须验证 |
|---|---|
| Review 服务 | 人工身份与原因、目标完整、强类型版本、质量 verdict、非 partial |
| Candidate loader | Manifest 文件集合、全部 hashes、Report/策略/来源 provenance |
| Repository promote 边界 | 人工 review-record.v2、批准版本、真实 Manifest partial、Report 与实际文件 |

任一 blocker、缺失 normalized、partial、缺少 provenance、hash 漂移、assessment/source 不一致都会
fail-closed。remediation patch 不是 ArtifactVariant，不能批准或发布。

## Publication Journal

| 状态 | 含义 | 恢复行为 |
|---|---|---|
| `preparing` | 已冻结发布 ID、版本、Review Records、目标 Snapshot 与备份 | provenance 有效则幂等完成，否则回滚 |
| `committed` | history、current、Review、Snapshot 与事件已完成 | 重复调用直接复用 |
| `rolled_back` | provenance 失效，已恢复发布前状态 | 不发布 |

只有 history、current、Review Record、Run Snapshot 和审核事件均完成后才能标记 committed。存储布局
和原子边界见[工作区与产物版本](artifact-versioning.md)。
