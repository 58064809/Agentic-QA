# CLI 参考

所有命令支持全局 `--repo-root`，默认当前目录。除 help、schema 和 `config init` 外，命令都要求根目录
`agentic-qa.local.yml` 有效；配置错误返回 2。

## 配置

| 命令 | 参数 | 行为 |
|---|---|---|
| `config init` | 无 | 从 example create-only 创建本地配置；不覆盖 |
| `config doctor` | 无 | 检查完整 Schema、路径、模型/RAG Key、数据库、连接器与全部 API 环境 |
| `config migrate` | `--output PATH` | create-only 将 v1 拆分为 v2；不推断外部 datasource |
| `config runtime-key init` | 无 | 仅在缺失时生成 cleanup journal 加密 Key，不覆盖现有 Key |
| `config secrets migrate` | 无 | 将旧版内联敏感值一次性迁移到 local Secret Provider；已有 provider 时拒绝覆盖 |

## Knowledge 管理

| 命令 | 参数 | 行为 |
|---|---|---|
| `knowledge migrate` | 无 | 在 system database 上用 advisory lock 执行前向迁移 |
| `knowledge status WORKSPACE` | workspace | 返回文档/chunk 数和 publication outbox 状态 |
| `knowledge index-run WORKSPACE RUN` | workspace、run | 对已人工审核并发布的 run 做幂等补偿索引 |
| `knowledge reindex WORKSPACE --published` | `--published` | 重新验证并重建已发布历史；不扫描 Candidate |
| `knowledge delete WORKSPACE --document-id ID` | workspace、document ID | 清除内容并保留 tombstone |

这些管理写操作不在 AgentRequest、MCP 或 Agent tool allowlist 中。

离线质量门使用 `python -m harness eval retrieval` 单独运行 Retrieval Golden；
`python -m harness eval run` 也包含相同的 Recall@10、MRR、source hit 与隔离泄漏门。

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
python -m harness failure collect <workspace> <execution-id> [--case-id <case/dataset-id>] [--source logs|traces|all]
python -m harness failure analyze <workspace> <execution-id> [--case-id <case/dataset-id>] [--collection-id <id>]
python -m harness failure report <workspace> <execution-id> [--case-id <case/dataset-id>] [--collection-id <id>]
```

`failure collect` 是显式触发的只读 evidence 采集，`--source` 默认是 `logs`，也可选择 `traces`
或 `all`。默认选择 ExecutionEvidence 中全部 `failed`，以及已经发送请求的 `error` 实例；blocked
和未发送请求的 error 不查询 Provider。成功或有效空结果返回
0，部分 provider 失败返回 1，配置、身份、生产环境或 hash 错误返回 2。产物写入对应 execution
的 create-only `triage/collections/<collection-id>/`，重复相同输入复用原 collection。
`failure analyze` 从存在的 Evidence 生成确定性 `log-analysis.json`、`trace-analysis.json` 和
`root-cause-graph.json`；随后调用受限 `failure_triager` 模型，Runtime/Live Eval 共用同一 Engine，且只提供脱敏派生
事实及 `EXEC-*`/`LOG-*`/`TRACE-*` 允许引用表，并写入 `failure-triage.json`。模型或校验失败时
`triage_status=failed`，命令返回 1；有效的 `insufficient_evidence` 返回 0。
同一 case/dataset 存在多个 collection 且未指定 `--collection-id` 时，`analyze/report` fail closed，
避免用文件时间推测用户意图。
`failure report` 为每个 collection 创建独立 triage run。`failure_analysis` 始终进入 Candidate；
只有产品、依赖、数据库等具有有效引用且至少 probable 的结果才增加 `bug_draft`。后续继续使用
`run diff` 与 `run review`，命令本身不批准、不发布，也不创建外部 Issue。

| 命令 | 关键参数 |
|---|---|
| `workspace create WORKSPACE` | 可重复 `--quality-policy` |
| `run start WORKSPACE GOAL` | 可重复 `--artifact`；`--requirement-baseline-run-id` 选择已发布 Delta baseline；API 产物由 `api prepare` 生成 |
| `run get WORKSPACE RUN` | 读取快照 |
| `run resume WORKSPACE RUN` | 只恢复可恢复执行，不代替 Review |
| `run diff WORKSPACE RUN ARTIFACT` | `--before`、`--after` |
| `run review WORKSPACE RUN DECISION` | `--reason`、`--reviewed-by`；批准 normalized 时显式 `--variant artifact=normalized` |

## 评测

```powershell
python -m harness eval run
python -m harness eval live --case order-lifecycle --output-dir .\build\live-eval
python -m harness eval failure-triage-live
```

Live Eval 的 case 和输出目录是一次性 CLI 选择，不再读取 `AGENTIC_QA_LIVE_EVAL_CASE` 或
`AGENTIC_QA_LIVE_EVAL_OUTPUT`。
`eval run` 包含离线 Failure Triage 契约/安全与 Trace root-cause Golden；`failure-triage-live` 使用当前模型路由和当前
分诊 Prompt，属于独立 Nightly Live Eval。

## Agent Request 与 MCP

`request run FILE`、`request schema` 和 `mcp serve` 保持受限来源 allowlist。它们不暴露 Review 写入、
approve、promote、shell 或任意文件读取能力。
