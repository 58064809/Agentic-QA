# Harness v2 公开契约

公开入口只有以下六个同步方法：

- `create_workspace(CreateWorkspaceCommand) -> Path`
- `start_run(StartRunCommand) -> RunSnapshot`
- `stream_run(StartRunCommand) -> Iterator[HarnessEvent]`
- `get_run(RunRef) -> RunSnapshot`
- `resume_run(ResumeRunCommand) -> RunSnapshot`
- `review_run(ReviewRunCommand) -> RunSnapshot`

Harness 控制面 Schema 使用 `agentic-qa.harness.*.v2`。所有 run 操作必须同时携带
`workspace_id` 与 `run_id`，运行时不会跨工作区扫描 run ID。旧 workspace 不迁移；加载非 v2
`workspace.yml` 时明确拒绝，并要求创建新的 v2 workspace。

`resume_run` 只恢复 `planning`、`running` 或 `recoverable` 状态下的崩溃执行，并继续使用
PostgreSQL 中相同 `workspace_id + run_id` thread 的 checkpoint。`review_run` 只处理
`needs_human_review` 或 `partial` 状态下的人工决定，两者不能互相替代。

`StartRunCommand` 包含目标、期望产物和 `ExecutionProfile`。目标中的 Bearer/Basic 凭据、
密钥赋值或私钥头会在持久化前拒绝。workspace ID 必须是安全的单层目录名，允许 Unicode
与内部空格，但拒绝路径分隔符、控制字符、Windows 保留名及尾随点。

计划进入执行前必须验证 Agent、依赖、产物生产者和证据要求。测试设计类产物必须直接依赖
需求分析与风险分析。公开契约不包含 LangGraph 类型，也不接受任意 Python 策略导入路径。

状态集合为 `planning`、`running`、`needs_human_review`、`partial`、`rejected`、
`needs_revision`、`published`、`failed` 和 `recoverable`。API 机器用例契约独立保持
`agentic-qa.api-cases.v1.1`。
