# 从零开始

本流程使用 PowerShell、workspace `demo` 和默认 `analysis-only` 模式生成 `testcases`。

如果希望 Codex、Claude、Cursor 等 AI 直接理解本地绝对路径并启动生成，请先看
[跨 AI 接入](agent-integration.md)。该入口自动完成本页第 3～4 步，但仍停在人工 Review Gate。

## 1. 安装

```powershell
Set-Location D:\TestHome\Agentic-QA
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m harness --help
```

本文使用 `python -m harness`，避免虚拟环境中残留旧 console entry point。重新执行 editable install
后，`agentic-qa` 与它等价。

## 2. 注入本机配置

```powershell
$env:DEEPSEEK_API_KEY = "<你的模型密钥>"
$env:PG_LOCAL_PASSWORD = "<你的 PostgreSQL 密码>"
```

PostgreSQL 默认连接：`localhost:5432/postgres`，用户为 `postgres`。不同连接通过 `PG_LOCAL_*`
变量覆盖。`.env.example` 只是清单，CLI 不自动读取 `.env`；完整说明见[配置参考](configuration.md)。

## 3. 创建 workspace 并放入来源

```powershell
python -m harness workspace create demo
Copy-Item D:\Docs\login-prd.md .\workspaces\demo\sources\
```

workspace 只创建一次。PRD、规则说明、OpenAPI 等文件必须在启动 run 前放入 `sources/`。run 启动后
会冻结 Source Bundle；修改当前 `sources/` 不会影响旧 run。

普通项目不需要传 `--quality-policy`。只有确实使用对应业务规则时才显式选择
`city-opening-rewards`。

## 4. 启动并保存 run_id

```powershell
$result = python -m harness run start demo "分析登录需求并生成测试用例" |
  ConvertFrom-Json

$runId = $result.run_id
$result.status
```

未指定 artifact 时默认生成 `testcases`。正常执行会停在 `needs_human_review`，这表示 Candidate 已等待
人工审核，不是失败。

生成多个产物时重复使用参数：

```powershell
$result = python -m harness run start demo "分析需求并输出测试用例和 QA 报告" `
  --artifact testcases `
  --artifact qa_report |
  ConvertFrom-Json
$runId = $result.run_id
```

## 5. 检查 Candidate

```powershell
$run = python -m harness run get demo $runId | ConvertFrom-Json
$run.candidates | Format-Table artifact, status, path, quality_report_path

$candidate = $run.candidates | Where-Object artifact -eq "testcases"
Get-Content -Encoding utf8 (Join-Path $PWD $candidate.path)
Get-Content -Encoding utf8 (Join-Path $PWD $candidate.quality_report_path)
```

审核至少确认：所选 variant 已通过、没有 blocker、不是 partial、来源和待确认项真实可追踪。

若同时存在 `raw` 与 `normalized`，先比较：

```powershell
python -m harness run diff demo $runId testcases --before raw --after normalized
```

`raw` 是 Agent 原始内容；`normalized` 只能包含不改变业务语义的格式调整。首次发布前不存在
`published` diff 端点。

## 6. 人工审核与发布

批准 raw：

```powershell
python -m harness run review demo $runId approve `
  --artifact testcases `
  --variant testcases=raw `
  --reason "已核对覆盖、断言、证据和待确认项" `
  --reviewed-by "qa-owner"
```

批准 normalized 时改用 `--variant testcases=normalized`。多 Candidate 一起批准必须指定 `all`，并为
每个 artifact 重复提供一个 `--variant`。

发布成功后读取：

```text
workspaces/demo/published/testcases/current.md
workspaces/demo/published/testcases/history/
```

## 7. 不批准时

| 决定 | 用途 | 后续 |
|---|---|---|
| `hold` | 等待外部确认 | 保留 Candidate，之后可继续审核 |
| `reject` | 明确拒绝 | 不发布 |
| `revise` | 记录修订要求 | 更新来源或目标后创建新 run |

```powershell
python -m harness run review demo $runId revise `
  --artifact testcases `
  --reason "缺少账号锁定边界" `
  --revision-request "补充失败次数边界和恢复场景" `
  --reviewed-by "qa-owner"
```

修订不覆盖旧 Candidate。`resume` 只用于 planning、running 或 recoverable 状态的崩溃恢复；正常停在
`needs_human_review` 或 `on_hold` 时应使用 `run review`。

## 常见失败

| 错误 | 处理 |
|---|---|
| `No module named 'harness.cli'` | 重新执行 `python -m pip install -e ".[dev]"`，或使用 `python -m harness` |
| 未配置模型 | 确认当前 shell 可读取模型 API Key |
| PostgreSQL password 未设置 | 设置 `PG_LOCAL_PASSWORD` 并确认服务运行 |
| approve 要求 variant | 检查 diff 后明确选择 `artifact=raw|normalized` |
| approve 被质量门拒绝 | 查看 `quality-report.json`，修正后创建新 run |
| 旧 run 未读取新 sources | 这是冻结行为；创建新 run |
| AgentRequest 路径被拒绝 | 将路径放在 MCP/CLI 的 `--allow-source-root` 内 |

全部命令和参数见 [CLI 参考](cli-reference.md)。
