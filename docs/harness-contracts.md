# Harness 公开契约

公开入口：

- `Harness.run(TaskRequest) -> RunSnapshot`
- `Harness.stream(TaskRequest) -> Iterator[HarnessEvent]`
- `Harness.resume(run_id, ReviewDecision | None = None) -> RunSnapshot`
- `Harness.inspect(run_id) -> RunSnapshot`

契约版本统一使用 `agentic-qa.harness.*.v1`。`TaskRequest` 包含 workspace、目标、期望产物和
execution profile；`QAPlan` 的任务明确依赖、Agent、输入、输出和证据要求；manifest 声明
Schema、allowlist、风险和限制，Skill 可引用随包发布的内置 QA 知识。无 ReviewDecision
的 `resume` 恢复可恢复执行；带决定时
只恢复 Review interrupt。

Harness 接受主管计划前会验证每个任务引用已注册 Agent、声明至少一项 evidence requirement，
并保证每个公开期望产物只有一个正确角色的生产者；缺失项进入 planner feedback 后重新生成，
不会把“Prompt 中要求过”当作已经满足。

workspace ID 是最长 128 字符的安全单层目录名，允许 Unicode 和内部空格，拒绝路径分隔符、
控制字符、Windows 保留名及尾随点。Agent 产物的确定性校验失败事件属于运行记录，不改变
公开状态枚举。

`ExecutionProfile` 默认是 `analysis-only`。非分析执行的 environment 必须存在于 workspace 的
`execution.environments`，且 base URL 环境变量必须一致、HTTP 方法必须是策略子集、UI mutation
和请求超时不得超过策略。`prod`、`production`、`live` 等 production-like 环境不受支持。
`TaskRequest.goal` 若包含 Bearer/Basic 凭据、密钥赋值或私钥头，会在创建 run 前拒绝；密钥应只
通过环境变量配置。外部工具和 source 文本中的同类片段在进入记录或模型上下文前统一脱敏。

状态只使用 `planning`、`running`、`needs_human_review`、`partial`、`rejected`、
`needs_revision`、`published`、`failed` 和 `recoverable`。`RunSnapshot` 同时公开待处理任务、
委派、工具调用、模型 usage、模型路由、预算和 interrupt 摘要。不加载旧状态别名。
