# Agentic-QA v2 命令

CLI 只组装命令对象并调用 `Harness`：

```powershell
agentic-qa workspace create <workspace_id> [--quality-policy city-opening-rewards]

agentic-qa run start <workspace_id> "<测试目标>" `
  [--artifact testcases] [--artifact qa_report] `
  [--environment <analysis-only|测试环境名>] `
  [--base-url-env AGENTIC_QA_BASE_URL] `
  [--allow-http-method GET] [--allow-ui-mutations] `
  [--request-timeout-seconds 10]

agentic-qa run get <workspace_id> <run_id>
agentic-qa run resume <workspace_id> <run_id>
agentic-qa run review <workspace_id> <run_id> <approve|reject|revise|hold|show_diff> `
  [--artifact <artifact|all>] --reason "<人工决定原因>" `
  --reviewed-by <审核人> [--revision-request "<修订要求>"]

agentic-qa eval run
```

`run resume` 只处理崩溃恢复，不接受审核决定。`run review` 只处理人工审核；多候选状态变更必须
指定单个 artifact 或 `all`。非 analysis-only 执行环境必须先在 `workspace.yml` 中登记，命令
参数只能收窄权限。
