# Agentic-QA v2 命令使用手册

这份文档按“第一次使用 → 生成 Candidate → 人工审核 → 发布”的顺序说明。第一次使用时，建议
直接照着“最短可用流程”执行，不需要先理解全部命令。

## 先理解三个概念

- `workspace_id`：一个项目或需求集合的名字，例如 `demo`。对应目录是
  `workspaces/demo/`。
- `run_id`：每次执行生成的唯一 ID。查询、恢复和审核时必须同时提供
  `workspace_id + run_id`。
- `Candidate`：Agent 生成的候选产物。它不会自动发布；人工审核通过后才会复制到
  `published/`。

默认命令只做 `analysis-only` 分析，不调用测试环境接口，也不执行 UI 写操作。

## 最短可用流程

以下示例假设仓库位于 `D:\TestHome\Agentic-QA`，workspace 名为 `demo`，目标是根据一份登录需求
生成测试用例。

### 1. 准备 Python 环境

```powershell
Set-Location D:\TestHome\Agentic-QA

# 仅第一次需要创建虚拟环境
python -m venv .venv

.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

# 确认当前 v2 CLI 可用
python -m harness --help
```

本文统一使用 `python -m harness`，这样不会受旧的命令入口缓存影响。执行过上面的 editable install
后，也可以把所有 `python -m harness` 替换成 `agentic-qa`。

如果 `agentic-qa` 报 `No module named 'harness.cli'`，说明虚拟环境中保留了旧入口。重新执行：

```powershell
python -m pip install -e ".[dev]"
```

### 2. 准备必要环境变量

启动 run 至少需要模型密钥和 PostgreSQL checkpoint 密码：

```powershell
$env:DEEPSEEK_API_KEY = "<你的 DeepSeek API Key>"
$env:PG_LOCAL_PASSWORD = "<你的本地 PostgreSQL 密码>"
```

本地 PostgreSQL 默认连接为：

```text
host=localhost  port=5432  database=postgres  user=postgres
```

如果实际连接不同，再设置对应变量：

```powershell
$env:PG_LOCAL_HOST = "localhost"
$env:PG_LOCAL_PORT = "5432"
$env:PG_LOCAL_DATABASE = "postgres"
$env:PG_LOCAL_USER = "postgres"
```

`.env.example` 只是变量清单和占位模板，CLI **不会自动加载 `.env` 文件**。可以把变量配置成 Windows
用户环境变量并重新打开终端，也可以像上面一样只对当前 PowerShell 会话设置。不要把真实密钥或密码
写入仓库文件。

完整变量说明见 [docs/configuration.md](docs/configuration.md)。

### 3. 创建 workspace

每个 workspace 只需创建一次：

```powershell
python -m harness workspace create demo
```

执行后会生成：

```text
workspaces/demo/
├── workspace.yml
├── sources/
├── runs/
├── candidates/
├── reviews/
└── published/
```

普通项目不要添加业务策略，默认通用质量策略会自动生效。只有确实需要“开城奖励”规则时才使用：

```powershell
python -m harness workspace create city-demo `
  --quality-policy city-opening-rewards
```

### 4. 放入需求资料

在启动 run **之前**，把 PRD、规则说明、OpenAPI 等资料复制到 workspace 的 `sources/`：

```powershell
Copy-Item D:\Docs\login-prd.md .\workspaces\demo\sources\
```

run 启动时会冻结这些来源。之后即使修改或新增 `sources/` 文件，已经启动的 run 仍只使用原快照；
需要使用新资料时必须创建新 run。

通用策略允许空 `sources/`，但没有需求依据时生成结果通常只能标记待确认。要求完整来源的业务策略会
直接阻止缺少来源的 Candidate 通过质量门。

### 5. 启动 run 并保存 run_id

```powershell
$result = python -m harness run start demo "分析登录需求并生成测试用例" |
  ConvertFrom-Json

$runId = $result.run_id
$runId
$result.status
```

未指定 `--artifact` 时默认生成 `testcases`。正常情况下，执行完成后状态会停在
`needs_human_review`，等待人工审核；这不是错误。

需要多个产物时重复传入 `--artifact`：

```powershell
$result = python -m harness run start demo "分析需求并输出测试用例和 QA 报告" `
  --artifact testcases `
  --artifact qa_report |
  ConvertFrom-Json

$runId = $result.run_id
```

可用 artifact 名称：

- `requirement_analysis`
- `testcases`
- `api_test_draft`
- `ui_test_draft`
- `api_discovery_report`
- `qa_report`
- `execution_report`
- `failure_analysis`
- `bug_draft`

### 6. 查看 Candidate 和质量报告

```powershell
$run = python -m harness run get demo $runId | ConvertFrom-Json
$run.status
$run.candidates | Format-Table artifact, status, path, quality_report_path
```

查看某个 Candidate 的原始内容和质量报告：

```powershell
$candidate = $run.candidates | Where-Object artifact -eq "testcases"
Get-Content -Encoding utf8 (Join-Path $PWD $candidate.path)
Get-Content -Encoding utf8 (Join-Path $PWD $candidate.quality_report_path)
```

重点检查 `quality-report.json` 中所选版本是否通过、是否存在 blocker，以及是否有待确认内容。
`raw` 是 Agent 原始内容，永远不会被质量策略覆盖；`normalized` 只包含不改变业务语义的机械格式调整。

如果 Candidate 同时存在 `raw` 和 `normalized`，可以先查看差异：

```powershell
python -m harness run diff demo $runId testcases `
  --before raw `
  --after normalized
```

首次发布前不能使用 `published` 端点；只有该 artifact 已经存在 published current 时，才能比较
`published` 与本次 Candidate。

### 7. 人工审核并发布

明确批准 `testcases` 的 raw 版本：

```powershell
python -m harness run review demo $runId approve `
  --artifact testcases `
  --variant testcases=raw `
  --reason "已核对需求覆盖、断言和待确认项" `
  --reviewed-by "qa-owner"
```

如果要批准 normalized 版本，把选择改为：

```powershell
--variant testcases=normalized
```

多个 Candidate 一起批准时，每个 artifact 都必须明确选择一个版本：

```powershell
python -m harness run review demo $runId approve `
  --artifact all `
  --variant testcases=raw `
  --variant qa_report=raw `
  --reason "全部候选已完成人工审核" `
  --reviewed-by "qa-owner"
```

系统会再次校验 Candidate manifest、质量报告、partial 状态和所有 hash。只有人工决定与质量门都通过，
才会发布到：

```text
workspaces/demo/published/testcases/current.md
workspaces/demo/published/testcases/history/
```

## 不批准时怎么处理

### 暂缓决定

```powershell
python -m harness run review demo $runId hold `
  --artifact testcases `
  --reason "等待产品确认登录锁定规则" `
  --reviewed-by "qa-owner"
```

HOLD 会留下审核记录并把状态设为 `on_hold`，不会修改 Candidate。之后仍可继续 approve、reject
或 revise。

### 拒绝

```powershell
python -m harness run review demo $runId reject `
  --artifact testcases `
  --reason "需求依据不足，不能发布" `
  --reviewed-by "qa-owner"
```

### 要求修订

```powershell
python -m harness run review demo $runId revise `
  --artifact testcases `
  --reason "缺少账号锁定边界用例" `
  --revision-request "补充第 4、5 次失败以及锁定恢复场景" `
  --reviewed-by "qa-owner"
```

修订不会覆盖旧 Candidate。审核完成后，应使用更新后的来源或更明确的目标启动一个**新 run**：

```powershell
python -m harness run start demo "根据审核意见补充账号锁定边界和恢复场景"
```

## `resume` 什么时候使用

`resume` 只用于进程崩溃或连接中断后的执行恢复：

```powershell
python -m harness run resume demo $runId
```

正常停在 `needs_human_review` 或 `on_hold` 时不要使用 `resume`，应使用 `run review`。修订也不要
使用 `resume`，应创建新 run。

## 非 analysis-only 测试环境

需要真实调用测试 API 或执行 UI mutation 时，必须先在 `workspaces/<workspace_id>/workspace.yml`
的 `execution.environments` 中登记测试环境和最大权限，再通过命令申请其子集。不要登记生产环境。

示例命令形式：

```powershell
python -m harness run start demo "验证测试环境登录接口" `
  --environment qa `
  --base-url-env AGENTIC_QA_BASE_URL `
  --allow-http-method GET `
  --allow-http-method POST `
  --request-timeout-seconds 10
```

仅传命令参数不能扩大 `workspace.yml` 中登记的权限。具体配置见
[docs/configuration.md](docs/configuration.md)。

## 在仓库目录外执行

默认 repo root 是当前目录。如果命令不在仓库根目录执行，必须把 `--repo-root` 放在子命令之前：

```powershell
python -m harness --repo-root D:\TestHome\Agentic-QA run get demo $runId
```

## 其他命令

运行离线评估：

```powershell
python -m harness eval run
```

查看各级帮助：

```powershell
python -m harness --help
python -m harness workspace create --help
python -m harness run start --help
python -m harness run review --help
```

CLI 成功返回退出码 `0`，参数或运行错误返回退出码 `2`，错误原因写到 stderr。

## 常见问题

### 提示未配置模型

确认当前终端能读取密钥：

```powershell
Test-Path Env:DEEPSEEK_API_KEY
```

### 提示 PostgreSQL password environment variable is not set

设置 `PG_LOCAL_PASSWORD`，并确认 PostgreSQL 服务正在运行。若刚配置 Windows 用户环境变量，需要
重新打开 PowerShell。

### Approve 提示必须显式指定 variant

Candidate 存在 normalized 版本。人工检查差异后，明确传入
`--variant artifact=raw` 或 `--variant artifact=normalized`。

### Approve 被质量门拒绝

查看 Candidate 目录中的 `quality-report.json`。partial、blocker、hash/provenance 不一致都不能发布。
不得绕过 Review Gate；修正来源或目标后创建新 run。

### 修改了 sources，但旧 run 仍使用旧内容

这是预期行为。每个 run 使用启动时的冻结 Source Bundle；创建新 run 才会读取新来源。

### 旧 workspace 无法运行

v2 不迁移也不恢复 v1 workspace。请使用新的 workspace ID 执行 `workspace create`，旧数据会保持原样。

## 完整命令速查

```powershell
python -m harness workspace create <workspace_id> `
  [--quality-policy city-opening-rewards]

python -m harness run start <workspace_id> "<测试目标>" `
  [--artifact testcases] [--artifact qa_report] `
  [--environment <analysis-only|测试环境名>] `
  [--base-url-env AGENTIC_QA_BASE_URL] `
  [--allow-http-method GET] [--allow-ui-mutations] `
  [--request-timeout-seconds 10]

python -m harness run get <workspace_id> <run_id>
python -m harness run resume <workspace_id> <run_id>

python -m harness run review <workspace_id> <run_id> <approve|reject|revise|hold> `
  [--artifact <artifact|all>] `
  [--variant <artifact=raw|artifact=normalized>] `
  --reason "<人工决定原因>" `
  --reviewed-by <审核人> `
  [--revision-request "<修订要求>"]

python -m harness run diff <workspace_id> <run_id> <artifact> `
  --before <published|raw|normalized> `
  --after <published|raw|normalized>

python -m harness eval run
```
