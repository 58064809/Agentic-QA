# Harness 公开契约

公开入口：

- `Harness.run(TaskRequest) -> RunSnapshot`
- `Harness.stream(TaskRequest) -> Iterator[HarnessEvent]`
- `Harness.resume(run_id, ReviewDecision | None = None) -> RunSnapshot`
- `Harness.inspect(run_id) -> RunSnapshot`

契约版本统一使用 `agentic-qa.harness.*.v1`。`TaskRequest` 包含 workspace、目标、期望产物和
execution profile；`QAPlan` 的任务明确依赖、Agent、输入、输出和证据要求；manifest 声明
Schema、allowlist、风险和限制。无 ReviewDecision 的 `resume` 恢复可恢复执行；带决定时
只恢复 Review interrupt。

状态只使用 `planning`、`running`、`needs_human_review`、`partial`、`rejected`、
`needs_revision`、`published`、`failed` 和 `recoverable`。`RunSnapshot` 同时公开待处理任务、
委派、工具调用、模型 usage、模型路由、预算和 interrupt 摘要。不加载旧状态别名。
