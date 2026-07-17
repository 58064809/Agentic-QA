# 失败分诊

失败分诊只依据 `agentic-qa.execution-evidence.v1` 生成
`agentic-qa.failure-triage.v1`。只有实际失败断言可关联 Bug 候选；execution error 和
policy blocked 只记录 observation。没有补充证据时 root cause 必须是 `unconfirmed`。
