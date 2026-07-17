# 产物标准

当前 Harness 管理 requirement_analysis、testcases、api_test_draft、ui_test_draft、
api_discovery_report、qa_report、execution_report、failure_analysis 和 bug_draft。

所有内容先作为 run 候选，必须说明证据和待确认项。执行证据使用
`agentic-qa.execution-evidence.v1`，失败分诊使用 `agentic-qa.failure-triage.v1`。
error/blocked 不得生成 Bug 候选。候选不得把 `needs_human_review` 表述为已确认。
