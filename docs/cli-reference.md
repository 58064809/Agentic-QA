# CLI 参考

本页用于查询命令位置、参数默认值、系统响应和退出码；完整操作示例见[从零开始](getting-started.md)。

## 调用形式

```powershell
python -m harness [--repo-root PATH] <command>
```

`--repo-root` 是顶层参数，解析位置在子命令之前；省略时使用当前目录。

## 命令

| 命令 | 必需参数 | 主要作用 |
|---|---|---|
| `workspace create` | `workspace_id` | 创建 v2 workspace；可重复指定 `--quality-policy` |
| `run start` | `workspace_id goal` | 冻结来源并执行到 Review Gate |
| `run get` | `workspace_id run_id` | 只读返回 RunSnapshot |
| `run resume` | `workspace_id run_id` | 恢复 recoverable run |
| `run review` | `workspace_id run_id decision` | 写人工 Review；approve 可触发发布 |
| `run diff` | `workspace_id run_id artifact` | 比较 raw、normalized 或 published |
| `eval run` | 无 | 运行离线工作流 Eval 和五类脱敏 Golden Eval |
| `eval live` | 无 | 使用显式配置的模型密钥生成 nightly Candidate，不发布 |
| `request run` | `request_file` | 导入允许根内的来源并幂等执行到 Review Gate |
| `request schema` | 无 | 输出 AgentRequest v1 JSON Schema |
| `mcp serve` | 无 | 启动受限的 stdio MCP Server |
| `api prepare` | `source_directory` | 幂等导入 API 目录，经单 Agent 快线生成 Candidate |
| `api execute` | `workspace_id run_id` | 按 workspace policy 执行 published API YAML |
| `api export-pytest` | `workspace_id` | 从 published API YAML 确定性导出 pytest adapter |

## `run start`

| 参数 | 默认值 | 系统行为 |
|---|---|---|
| `--artifact` | `testcases` | 可重复；未知 artifact 返回参数错误 |
| `--environment` | `analysis-only` | production-like 名称被安全校验拒绝 |
| `--base-url-env` | 空 | 非 analysis-only 时与 workspace policy 比对 |
| `--allow-http-method` | `GET, HEAD, OPTIONS` | 超出 workspace policy 的方法被拒绝 |
| `--allow-ui-mutations` | false | workspace 未授权时返回权限错误 |
| `--request-timeout-seconds` | `10` | 接受 1–60 秒，并与 workspace policy 上限比对 |

Artifact：`requirement_analysis`、`testcases`、`api_test_draft`、`ui_test_draft`、
`api_discovery_report`、`qa_report`、`execution_report`、`failure_analysis`、`bug_draft`。

## `run review`

| decision | version | 发布 | 结果 |
|---|---:|---:|---|
| `approve` | 每个目标恰好一个 | 复验通过后发布 | `published` 或其余 artifact 状态 |
| `hold` | 不需要 | 否 | `on_hold` |
| `reject` | 不需要 | 否 | `rejected` |
| `revise` | 不接收版本；缺少 `--revision-request` 时返回参数错误 | 否 | `needs_revision` |

多 Candidate 时，`--artifact` 接受单个 artifact 或 `all`；缺少目标会返回歧义错误。approve 通过
可重复的 `--variant artifact=raw|normalized` 明确选择版本，CLI 不代替审核人决定。

## `run diff`

`--before` 与 `--after` 接受 `raw`、`normalized` 或 `published`。remediation patch 不属于
ArtifactVariant，因此不会出现在差异端点或发布版本中。

## `request` 与 `mcp`

`request run` 接受 JSON/YAML。`local-sources/requirements/` 是默认允许根；额外根使用可重复的
`--allow-source-root`。AgentRequest 固定为 analysis-only，不暴露 Review、approve、promote、shell
或任意文件读取工具。

## `api`

`api prepare SOURCE_DIRECTORY` 要求目录内至少有一份自包含 OpenAPI 3.x/Swagger 2.0 和一份合法人工
用例。支持标准 11 列 Markdown/CSV 与 `agentic-qa.test-case-set.v1` YAML；外部 `$ref`、重复用例 ID、
错误列数或非法 YAML 在模型调用前失败。其他文件列入 ignored 清单。

| `api prepare` 参数 | 默认值 | 系统行为 |
|---|---|---|
| `--goal` | 组装契约约束 API 场景 | 只描述场景组装目标，不接受疑似密钥 |
| `--workspace-id` / `--request-id` | 自动派生 / 空 | 相同请求与来源哈希返回同一 run |
| `--environment` | 必填 | 拒绝 production-like 名称 |
| `--base-url-env` | `AGENTIC_QA_BASE_URL` | 只保存环境变量名，不保存 URL 值 |
| `--trusted-origin` | 必填、可重复 | 只接受 HTTPS Origin |
| `--allow-http-method` | 必填、可重复 | 冻结为 workspace 方法 allowlist |
| `--request-timeout-seconds` | `10` | 作为 workspace 最大请求超时，接受 1–60 |
| `--api-auth-config` | 空 | JSON/YAML 认证配置；静态 Token 只接受 `token_env` |
| `--quality-policy` | 空 | 可重复选择已注册质量策略 |

快线固定只创建一个 `api_test_engineer` 任务，跳过模型 Planner、Requirement 和 Risk 任务，但保留质量
修订循环及人工 Review Gate。系统要求每个人工用例 ID 均由 `manual-test-case` source ref 映射；契约无法确认的
步骤保持 pending/unconfirmed，不补造 endpoint。

`api execute` 默认读取 `published/api_test_draft/current.yml`。缺少显式
`--environment` 或至少一个 `--allow-http-method` 时，CLI 返回参数错误；`--base-url-env` 默认是
`AGENTIC_QA_BASE_URL`，所有值仍须通过 workspace policy 校验。

`api export-pytest` 默认写入 `exports/api_test_draft/test_api_cases.py`。非 `published/` 来源或
`exports/` 以外的输出返回错误；目标已存在时拒绝，显式 `--overwrite` 表示同意替换。导出文件
绑定 published YAML 的 SHA-256，并在 pytest 执行时调用公开 Harness API。导出的测试按业务用例、
dataset 实例和 cleanup Evidence ID 分项报告，场景请求在同一个 pytest session 中只执行一次。

## Eval

`eval run` 不需要模型密钥，包含：

- recorded workflow、MCP snapshot、Review Gate 和 deterministic promote；
- login-lock、order-refund、coupon-boundary、settlement-rounding、lottery-assistance、
  city-opening-rewards 六类脱敏设计 Golden Case。每个 Case 分别读取
  `expectations.json`、`baseline-testcases.json`、
  `candidate-requirement-catalog.json` 和 `candidate-testcases.md`；候选缺失时失败，
  并报告 `baseline_score` 与 `baseline_gap`，不会把人工基线当成待测产物；
- 规则召回、覆盖率、幻觉率、重复率、边界/状态覆盖和可执行性评分。
- order-lifecycle API Golden Case，确定性评分 dataset、提取、跨请求引用、cleanup、断言类型与安全定义。

`eval live` 需要显式模型配置。默认场景是脱敏的 `login-lock`；环境变量
`AGENTIC_QA_LIVE_EVAL_CASE=lottery-assistance` 会切换到规则更密集的助力抽奖场景；设置为
`order-lifecycle` 时运行完整 OpenAPI 驱动的数据集、变量提取、跨请求引用与 cleanup API 场景。系统生成真实
隔离 Candidate，停在 Review Gate 后读取本次 raw artifact；设计场景计算规则召回、覆盖、幻觉、
重复、边界/状态和可执行性分数，API 场景计算数据驱动与请求链覆盖分数。状态正确但质量分不足仍返回
失败。设置 `AGENTIC_QA_LIVE_EVAL_OUTPUT` 时，只导出脱敏 `source-bundle.json`、本次 raw artifact、
`quality-report.json` 与 `generation-report.json` 供人工审查，不导出整个 workspace。

Nightly 每周单独运行 `order-lifecycle` API Live Eval，并上传 `api_test_draft` 的 raw、质量报告和生成报告。
API Golden 除能力点覆盖外，还按同一 OpenAPI 核对 operation、必填与未知参数、请求体字段、响应码、
响应 JSON 路径、响应头和提取来源；契约语义不一致时评分低于满分。

## 退出码

| 退出码 | 含义 |
|---:|---|
| `0` | 命令成功；Eval 通过 |
| `1` | Eval 完成但未通过 |
| `2` | 参数、配置或运行错误 |
