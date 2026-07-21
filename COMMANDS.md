# Agentic-QA 命令

CLI 是 `Harness` Python API 的薄封装，不复制规划、路由或 Prompt。

```powershell
agentic-qa workspace init <id>
agentic-qa run <id> "<测试目标>" [--artifact testcases] [--artifact qa_report] `
  [--environment <analysis-only|测试环境名>] [--base-url-env <环境变量名>] `
  [--allow-http-method GET] [--allow-ui-mutations] [--request-timeout-seconds 10]
agentic-qa inspect <run_id>
agentic-qa resume <run_id>
agentic-qa resume <run_id> <approve|reject|revise|hold|show_diff> `
  [--artifact <artifact|all>] --reason "<人工决定原因>"
agentic-qa agents list
agentic-qa skills list
agentic-qa tools list
agentic-qa eval run
```

多候选的 `approve`、`reject` 或 `revise` 必须通过 `--artifact` 指定单个产物或 `all`。
无审核决定的 `resume` 用于恢复崩溃执行；只有 `approve` 会触发确定性 promote。
旧 Runtime CLI 和 `prd/...` 参数不受支持。
