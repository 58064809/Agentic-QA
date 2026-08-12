# CLI 参考

所有命令支持全局 `--repo-root`，默认当前目录。除 help、schema 和 `config init` 外，命令都要求根目录
`agentic-qa.local.yml` 有效；配置错误返回 2。

## 配置

| 命令 | 参数 | 行为 |
|---|---|---|
| `config init` | 无 | 从 example create-only 创建本地配置；不覆盖 |
| `config doctor` | 无 | 检查完整 Schema、路径、模型/RAG Key、数据库、连接器与全部 API 环境 |
| `config runtime-key init` | 无 | 仅在缺失时生成 cleanup journal 加密 Key，不覆盖现有 Key |
| `config secrets migrate` | 无 | 将旧版内联敏感值一次性迁移到 local Secret Provider；已有 provider 时拒绝覆盖 |

## API 垂直链路

| 命令 | 位置参数 | 选项 | 成功行为 |
|---|---|---|---|
| `api doctor` | `SOURCE_DIRECTORY` | `--environment NAME` | 只读预检 |
| `api prepare` | `SOURCE_DIRECTORY` | `--environment NAME`、`--goal`、`--workspace-id`、`--request-id`、重复 `--quality-policy` | 生成 Candidate 并停在 Review Gate |
| `api run` | `WORKSPACE EXECUTION_ID` | `--environment NAME` | 执行 published YAML 并持久化报告 |
| `api report allure` | `WORKSPACE EXECUTION_ID` | 无 | 从既有执行结果生成 Allure 3 HTML，不重放请求 |
| `api cleanup resume` | `WORKSPACE EXECUTION_ID` | `--environment NAME` | 只执行加密 journal 中从未发送的 pending cleanup |
| `api execute` | `WORKSPACE RUN_ID` | `--environment NAME`、`--cases-path` | 公开执行用例；不提供内联安全策略 |
| `api export-pytest` | `WORKSPACE` | `--cases-path`、`--output-path`、`--overwrite` | 导出绑定环境与 YAML hash 的 pytest 壳 |

`api prepare` 不再接受 `--base-url-env`、`--trusted-origin`、`--allow-http-method` 或认证文件；这些持久
策略统一写入根配置。`api run` 返回 0/1/2，分别表示全部通过、存在执行失败、命令或配置错误。

## Run 与 Review

### Failure Triage

```powershell
python -m harness failure collect <workspace> <execution-id> [--case-id <case/dataset-id>]
python -m harness failure analyze <workspace> <execution-id> [--case-id <case/dataset-id>] [--collection-id <id>]
```

`failure collect` 是显式触发的只读日志采集。默认选择 ExecutionEvidence 中全部 `failed`，以及
已经发送请求的 `error` 实例；blocked 和未发送请求的 error 不查询日志。成功或有效空结果返回
0，部分 provider 失败返回 1，配置、身份、生产环境或 hash 错误返回 2。产物写入对应 execution
的 create-only `triage/collections/<collection-id>/`，重复相同输入复用原 collection。
`failure analyze` 从已验证的 Log Evidence 生成确定性 `log-analysis.json`，其中 fingerprint、
occurrence、时间线和 `LOG-*` 引用均可复算；该命令不调用模型。

| 命令 | 关键参数 |
|---|---|
| `workspace create WORKSPACE` | 可重复 `--quality-policy` |
| `run start WORKSPACE GOAL` | 可重复 `--artifact`；API 产物由 `api prepare` 生成 |
| `run get WORKSPACE RUN` | 读取快照 |
| `run resume WORKSPACE RUN` | 只恢复可恢复执行，不代替 Review |
| `run diff WORKSPACE RUN ARTIFACT` | `--before`、`--after` |
| `run review WORKSPACE RUN DECISION` | `--reason`、`--reviewed-by`；批准 normalized 时显式 `--variant artifact=normalized` |

## 评测

```powershell
python -m harness eval run
python -m harness eval live --case order-lifecycle --output-dir .\build\live-eval
```

Live Eval 的 case 和输出目录是一次性 CLI 选择，不再读取 `AGENTIC_QA_LIVE_EVAL_CASE` 或
`AGENTIC_QA_LIVE_EVAL_OUTPUT`。

## Agent Request 与 MCP

`request run FILE`、`request schema` 和 `mcp serve` 保持受限来源 allowlist。它们不暴露 Review 写入、
approve、promote、shell 或任意文件读取能力。
