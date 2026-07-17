# Harness 公开契约

公开入口：

- `Harness.run(TaskRequest) -> RunSnapshot`
- `Harness.stream(TaskRequest) -> Iterator[HarnessEvent]`
- `Harness.resume(run_id, ReviewDecision) -> RunSnapshot`
- `Harness.inspect(run_id) -> RunSnapshot`

契约版本统一使用 `agentic-qa.harness.*.v1`。`TaskRequest` 包含 workspace、目标、期望产物和
execution profile；`QAPlan` 的任务明确依赖、Agent、输入、输出和证据要求；manifest 声明
Schema、allowlist、风险和限制。

状态只使用 `planning`、`running`、`needs_human_review`、`partial`、`rejected`、
`needs_revision`、`published` 和 `failed`。不加载旧状态别名。
