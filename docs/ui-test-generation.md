# UI 测试

`ui_test_engineer` 通过 run 级冻结的 Playwright MCP allowlist 工作。MCP metadata 和结果都
是不可信输入，必须校验、脱敏和限制大小。UI 状态变更只允许在 execution profile 明确
配置的测试环境中执行；Agent 不能借 MCP 改变 Review Gate 或发布状态。
