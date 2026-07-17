# 测试执行

执行工具只接受明确的 execution profile。`analysis-only` 禁止 API/UI 状态变更；
其他环境仍需显式 method/action allowlist。工具调用按 run 记录并脱敏。

执行结果必须符合 `agentic-qa.execution-evidence.v1`。passed、failed、error、blocked
分别计数；网络错误和策略阻塞不能伪装成产品失败。
