# 从零开始

本流程使用 PowerShell、workspace `demo` 和默认 `analysis-only` 模式生成 `testcases`。

如果希望 Codex、Claude、Cursor 等 AI 直接理解本地绝对路径并启动生成，请先看
[跨 AI 接入](agent-integration.md)。该入口自动完成本页第 3～4 步，但仍停在人工 Review Gate。

本地需求建议放在 `local-sources/requirements/<需求名>/`。该路径被 Git 忽略，任何 Harness 命令
首次运行时都会自动创建 `local-sources/requirements/`，clone 后无需手工建目录。

## 1. 安装

```powershell
Set-Location D:\TestHome\Agentic-QA
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,docs]" -c constraints.txt
python -m harness --help
.\scripts\cold-start-check.ps1
```

本文使用 `python -m harness`，避免虚拟环境中残留旧 console entry point。重新执行 editable install
后，`agentic-qa` 与它等价。`constraints.txt` 固定经过离线 Eval 和全量测试的依赖组合；修改
`pyproject.toml` 依赖后需重新生成并验证 constraints。

## 2. 注入本机配置

```powershell
$env:DEEPSEEK_API_KEY = "<你的模型密钥>"
$env:PG_LOCAL_PASSWORD = "<你的 PostgreSQL 密码>"
```

PostgreSQL 默认连接：`localhost:5432/postgres`，用户为 `postgres`。不同连接通过 `PG_LOCAL_*`
变量覆盖。`.env.example` 只是清单，CLI 不自动读取 `.env`；完整说明见[配置参考](configuration.md)。
PostgreSQL 服务本身也需要处于可连接状态。注入配置后可执行：

```powershell
.\scripts\cold-start-check.ps1 -Runtime
```

该检查只报告使用的密钥环境变量名，不打印密钥值；同时使用只建立后立即关闭的连接验证 PostgreSQL。
维护者需要运行完整仓库验收时使用 `-Full`，它会继续执行 Ruff、pytest、离线 Eval、严格文档构建和
wheel 构建。

## 3. 创建 workspace 并放入来源

```powershell
python -m harness workspace create demo
Copy-Item D:\Docs\login-prd.md .\workspaces\demo\sources\
```

workspace 只创建一次。run 启动时，系统从 `sources/` 读取 PRD、规则说明和 OpenAPI，并冻结为
Source Bundle；之后修改当前 `sources/` 不会影响旧 run。

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
$run.candidates |
  Format-Table artifact, status, path, quality_report_path, generation_report_path

$candidate = $run.candidates | Where-Object artifact -eq "testcases"
Get-Content -Encoding utf8 (Join-Path $PWD $candidate.path)
Get-Content -Encoding utf8 (Join-Path $PWD $candidate.quality_report_path)
Get-Content -Encoding utf8 (Join-Path $PWD $candidate.generation_report_path)
```

`generation-report.json` 明确记录是否使用 LLM、实际模型路由、Token、结构化输出重试和质量修订
次数。审核至少确认：所选 variant 已通过、没有 blocker、不是 partial、来源和待确认项真实可追踪。

若同时存在 `raw` 与 `normalized`，先比较：

```powershell
python -m harness run diff demo $runId testcases --before raw --after normalized
```

`raw` 是 Agent 原始内容；`normalized` 包含不改变业务语义的格式调整。首次发布前不存在
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

批准 normalized 时改用 `--variant testcases=normalized`。多 Candidate 一起批准时，`all` 表示全部
目标，每个 artifact 都有一个对应的 `--variant`；缺少选择会返回参数错误。

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

## 8. 从 Apifox 目录生成 API Candidate

从 Apifox 导出自包含的 OpenAPI 3.x 或 Swagger 2.0 文件，并将它与至少一份标准 11 列人工用例放在
同一目录。人工用例可使用同序表头的 Markdown、CSV（支持 UTF-8 BOM），或强类型
`agentic-qa.test-case-set.v1` YAML。目录中的其他文件只进入 ignored 清单，不发送给模型。

```powershell
$prepared = python -m harness api prepare D:\Docs\order-api `
  --workspace-id order-api `
  --environment qa `
  --base-url-env AGENTIC_QA_BASE_URL `
  --trusted-origin https://qa.example.test `
  --allow-http-method GET `
  --allow-http-method POST `
  --allow-http-method DELETE |
  ConvertFrom-Json
$apiRunId = $prepared.run_id
$apiWorkspace = $prepared.workspace_id
```

`api prepare` 安全导入并冻结整个目录，但只把归一化 OpenAPI 与人工用例交给单个 API Agent；它不调用
模型 Planner、Requirement 或 Risk Agent。重复相同请求返回同一 run。输出直接给出来源分类、Candidate、
质量报告、生成报告和下一步审核信息，并始终停在 Review Gate。

先检查差异，再批准明确版本：

```powershell
python -m harness run diff $apiWorkspace $apiRunId api_test_draft --before raw --after normalized
python -m harness run review $apiWorkspace $apiRunId approve `
  --artifact api_test_draft `
  --variant api_test_draft=raw `
  --reason "已核对人工用例映射、契约、数据链和 cleanup" `
  --reviewed-by "qa-owner"
```

若只有 raw 版本，省略 diff，并仍显式选择 `api_test_draft=raw`。人工用例无法由 OpenAPI 确认时，
系统会将这类 Candidate 保留为 unconfirmed/pending 场景；未映射 ID、partial、blocker 或来源哈希漂移均会阻止发布。

发布后，实际 base URL 和认证值只放在运行环境中。`api run` 从 workspace policy 派生 Origin、方法、
认证和超时，不在 CLI 重复接收这些安全策略：

```powershell
$env:AGENTIC_QA_BASE_URL = "https://qa.example.test"
$env:QA_API_TOKEN = "<QA 环境 Token>"
python -m harness api run $apiWorkspace trial-001 --environment qa
```

完成后可审查以下 create-only 产物：

```text
workspaces/<workspace>/executions/trial-001/manifest.json
workspaces/<workspace>/executions/trial-001/evidence.json
workspaces/<workspace>/executions/trial-001/summary.md
```

同一 execution ID 不会再次发送请求。进程在请求阶段中断时，manifest 保持或转为 `indeterminate`；
确认环境状态后使用新的 ID，不自动重放写请求。全部用例通过时退出码为 0；报告已落盘但含
failed/error/blocked 时为 1；配置、预检或命令错误为 2。

需要接入现有 pytest 流水线时，从已审核版本导出确定性 adapter：

```powershell
python -m harness api export-pytest demo
$env:AGENTIC_QA_EXECUTION_ENVIRONMENT = "qa"
$env:AGENTIC_QA_ALLOWED_HTTP_METHODS = "GET,POST,DELETE"
pytest -q .\workspaces\demo\exports\api_test_draft\test_api_cases.py
```

adapter 绑定 published YAML 的 SHA-256；发布内容更新后需重新导出。它不会生成另一份业务脚本逻辑，
也不会批准 Candidate，而是通过公开 Harness API 运行同一份数据集、变量提取、断言和 cleanup 语义。

## 常见失败

| 错误 | 处理 |
|---|---|
| `No module named 'harness.cli'` | 重新执行 `python -m pip install -e ".[dev,docs]" -c constraints.txt`，或使用 `python -m harness` |
| 未配置模型 | 确认当前 shell 可读取模型 API Key |
| PostgreSQL password 未设置 | 设置 `PG_LOCAL_PASSWORD` 并确认服务运行 |
| approve 要求 variant | 检查 diff 后明确选择 `artifact=raw|normalized` |
| approve 被质量门拒绝 | 查看 `quality-report.json`，修正后创建新 run |
| 旧 run 未读取新 sources | 这是冻结行为；创建新 run |
| AgentRequest 路径被拒绝 | 放入 `local-sources/requirements/`，或通过 `--allow-source-root` 追加外部目录 |
| execution ID 已存在 | 查看该目录 manifest；不重放，确认环境状态后使用新 ID |

全部命令和参数见 [CLI 参考](cli-reference.md)。
