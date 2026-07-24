# Harness v2 公开契约

## Facade 方法

| 方法 | 输入 | 输出 | 前置条件 | 写入/副作用 |
|---|---|---|---|---|
| `create_workspace` | `CreateWorkspaceCommand` | `Path` | workspace ID 安全且不存在 | 创建 v2 workspace |
| `start_run` | `StartRunCommand` | `RunSnapshot` | workspace、模型、PostgreSQL 可用 | 创建 run 并执行到终态/Review Gate |
| `stream_run` | `StartRunCommand` | `Iterator[HarnessEvent]` | 同 `start_run` | 同一执行的事件流 |
| `get_run` | `RunRef` | `RunSnapshot` | `workspace_id + run_id` 存在 | 只读；可触发未完成发布恢复 |
| `get_artifact_diff` | `GetArtifactDiffQuery` | `ArtifactDiffResult` | 两端版本存在 | 只读 |
| `resume_run` | `ResumeRunCommand` | `RunSnapshot` | planning/running/recoverable | 从同一 PostgreSQL thread 恢复 |
| `review_run` | `ReviewRunCommand` | `RunSnapshot` | run 可审核且人工决定有效 | 写 Review；approve 可发布 |

所有 run 操作显式携带 `workspace_id + run_id`，不全局扫描 run ID。控制面 Schema 使用
`agentic-qa.harness.*.v2`；API cases 独立保持 `agentic-qa.api-cases.v1.1`。

外部 AI 的 `AgentRequest` 和 MCP 是独立受限门面，不增加 Harness 的 Review 权限，也不改变上述
七个方法；其契约见[跨 AI 接入](agent-integration.md)。

## Candidate provenance

| 字段 | 用途 |
|---|---|
| `versions` | 实际存在的 raw/normalized 文件、路径和内容 hash |
| `assessment_key` | 固定本次来源、内容、Normalizer 和策略输入 |
| `quality_report_path/sha256` | 质量报告定位与完整性 |
| `generation_report_path/sha256` | LLM 使用、模型路由、Token、重试与质量修订审计 |
| `source_bundle_hash` | 绑定 run 的冻结来源 |
| `policy_versions` | 记录参与评估的策略版本 |
| `partial` | 从 Candidate Manifest 恢复；不是 Snapshot 的可信替代 |

`ArtifactCandidate` 不持久化 `quality_passed`。所选 variant 是否可发布由 Review 服务和 Repository
从质量报告派生，不是公开 Candidate 字段；内部事件中的 `publishable_variants` 也不是 Facade 契约。

## ArtifactVersionRef

| 字段 | 约束 |
|---|---|
| `artifact` | 必须是本次目标 Candidate |
| `variant` | 仅 `raw` 或 `normalized` |
| `content_sha256` | 必须匹配实际版本文件 |
| `assessment_key` | 必须匹配 Candidate 与质量报告 |
| `quality_report_sha256` | 必须匹配已提交报告 |

可使用 `candidate.version_ref(ArtifactVariant.RAW)` 构造。Approve 对每个目标恰好提供一个引用；CLI
对应重复的 `--variant artifact=raw|normalized`。

## 兼容边界

| 输入 | 行为 |
|---|---|
| v1 workspace | 明确拒绝，不迁移、不删除 |
| 缺少 Candidate provenance 的旧 v2 run | 只可查询，不可批准或发布 |
| `resume_run` 携带人工决定 | 类型契约不支持 |
| `review_run` 用于崩溃恢复 | 不支持；职责与 resume 分离 |
