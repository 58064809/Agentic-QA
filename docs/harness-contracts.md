# Harness v2 公开契约

公开入口保持六个同步方法：`create_workspace`、`start_run`、`stream_run`、`get_run`、
`resume_run` 和 `review_run`。所有 run 操作显式携带 `workspace_id + run_id`；控制面 Schema 使用
`agentic-qa.harness.*.v2`，API cases 独立保持 `agentic-qa.api-cases.v1.1`。

`ArtifactCandidate` 保存 raw 主路径、可用 ArtifactVersion、assessment key、source bundle hash、
策略版本和质量报告引用，不保存 `quality_passed`。调用方通过质量报告或 Review Gate 返回的
`publishable_variants` 获得派生状态。

Approve 的 ReviewDecision 必须提供 `versions: list[ArtifactVersionRef]`。ArtifactVersionRef 包含：

- artifact；
- `ArtifactVariant.RAW` 或 `ArtifactVariant.NORMALIZED`；
- content SHA-256；
- assessment key；
- quality report SHA-256。

可以使用 `candidate.version_ref(ArtifactVariant.RAW)` 构造引用。CLI 使用重复的
`--variant artifact=raw|normalized`；当 Candidate 存在 normalized 时必须显式选择。

`resume_run` 不接受人工决定，`review_run` 不承担崩溃恢复。v1 workspace 明确拒绝；旧的、缺少
Candidate provenance 的 v2 run 只可查询，不可批准或发布。
