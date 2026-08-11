# Harness v2 公开契约

本页面向 Python 集成者，说明 Facade 接受的强类型输入、返回值和可观察副作用。

## Facade 方法

| 方法 | 输入 | 输出 | 前置条件 | 写入/副作用 |
|---|---|---|---|---|
| `check_local_config` | 无 | `LocalConfigCheckResult` | 仓库根目录可读 | 只读检查根配置，不创建 workspace/run |
| `api_execution_profile` | `workspace, environment` | `ExecutionProfile` | workspace 已绑定 API 服务 | 只读派生执行配置，不返回凭据值 |
| `create_workspace` | `CreateWorkspaceCommand` | `Path` | workspace ID 安全且不存在 | 创建 v2 workspace |
| `check_api_project` | `ApiProjectCheckCommand` | `ApiProjectCheckResult` | 根配置与来源目录可读 | 只读检查根配置、运行环境和 API 来源，不创建 workspace/run |
| `prepare_api_scenario` | `ApiScenarioPrepareCommand` | `ApiScenarioPrepareResult` | 来源目录含完整 OpenAPI 与合法人工用例，且配置受控 QA 环境策略 | 幂等导入来源并生成单个 API Candidate；停在 Review Gate |
| `start_run` | `StartRunCommand` | `RunSnapshot` | workspace、模型、PostgreSQL 可用 | 创建 run 并执行到终态/Review Gate |
| `stream_run` | `StartRunCommand` | `Iterator[HarnessEvent]` | 同 `start_run` | 同一执行的事件流 |
| `get_run` | `RunRef` | `RunSnapshot` | `workspace_id + run_id` 存在 | 只读；可触发未完成发布恢复 |
| `get_artifact_diff` | `GetArtifactDiffQuery` | `ArtifactDiffResult` | 两端版本存在 | 只读 |
| `execute_api_cases` | `ExecuteApiCasesCommand` | `ExecutionEvidence` | published API YAML、测试环境策略和环境变量有效 | 发送允许的 API 请求；不写 Review 或 published |
| `run_api_scenario` | `RunApiScenarioCommand` | `RunApiScenarioResult` | published API YAML、workspace 环境策略和新的 execution ID 有效 | create-only 写 manifest v2、Evidence、哈希链日志、cleanup 状态和 Allure results/HTML；不自动重放 |
| `generate_api_allure_report` | `GenerateApiAllureReportCommand` | `GenerateApiAllureReportResult` | execution 已存在且包含 Allure results 或 Evidence | 生成静态 Allure HTML；不发送 API 请求 |
| `resume_api_cleanup` | `ResumeApiCleanupCommand` | `ResumeApiCleanupResult` | 加密 journal、环境、published hash 和策略 hash 一致 | 只发送 pending cleanup；不重放业务请求或不确定 cleanup |
| `export_api_pytest` | `ExportApiPytestCommand` | `ApiPytestExportResult` | 来源是 published API YAML，目标位于 workspace `exports/` | 确定性写入 pytest adapter；默认 create-only |
| `resume_run` | `ResumeRunCommand` | `RunSnapshot` | planning/running/recoverable | 从同一 PostgreSQL thread 恢复 |
| `review_run` | `ReviewRunCommand` | `RunSnapshot` | run 可审核且人工决定有效 | 写 Review；approve 可发布 |

所有 run 操作显式携带 `workspace_id + run_id`，不全局扫描 run ID。控制面 Schema 使用
`agentic-qa.harness.*.v2`；API cases 独立保持 `agentic-qa.api-cases.v1.2`。

外部 AI 的 `AgentRequest` 和 MCP 是独立受限门面，不增加 Harness 的 Review 权限，也不改变上述
十二个方法；其契约见[跨 AI 接入](agent-integration.md)。

pytest adapter 固定来源 YAML 的 SHA-256，执行时重新校验 hash。它调用同一公开
`execute_api_cases` 用例，不复制断言、变量或 cleanup 解释逻辑；workspace 执行策略与 Review Gate
仍然生效。

## API 执行认证

`ExecutionEnvironmentPolicy` 在声明 `base_url_env` 时同时保存非空 `trusted_origins`；每项是纯 HTTPS
Origin。公开 Harness API 和内置 `api.execute` 都在认证前校验实际 base URL 是否命中该 allowlist。

`ExecutionEnvironmentPolicy.api_auth` 是可选的判别联合：

| `mode` | 强类型配置 | 执行行为 |
|---|---|---|
| `static_token` | `StaticTokenApiAuthentication` | 从直接 `token` 或 `token_env` 二选一取值，按 `ApiTokenInjection` 注入请求头 |
| `login` | `LoginApiAuthentication` | 按 `ApiLoginRequest` 登录一次，从 `token_json_path` 提取并注入 token |

认证配置属于 workspace 执行策略，不进入 API Cases v1.1。`LoginApiAuthentication` 当前接受相对
POST 路径、预期状态码、JSON 点路径和 header 注入；敏感请求字段引用环境变量。配置解析、HTTP
method allowlist 和执行器共同确定是否发送登录及后续请求。

## Candidate provenance

| 字段 | 用途 |
|---|---|
| `versions` | 实际存在的 raw/normalized 文件、路径和内容 hash |
| `assessment_key` | 固定本次来源、内容、Normalizer 和策略输入 |
| `quality_report_path/sha256` | 质量报告定位与完整性 |
| `generation_report_path/sha256` | LLM 使用、模型路由、Token、重试与质量修订审计 |
| `source_bundle_hash` | 绑定 run 的冻结来源 |
| `policy_versions` | 记录参与评估的策略版本 |
| `attachments` | 补充机器产物的路径、媒体类型和内容 hash；API Discovery 使用脱敏目录 |
| `partial` | 从 Candidate Manifest 恢复；不是 Snapshot 的可信替代 |

`ArtifactCandidate` 不持久化 `quality_passed`。所选 variant 是否可发布由 Review 服务和 Repository
从质量报告派生，不是公开 Candidate 字段；内部事件中的 `publishable_variants` 也不是 Facade 契约。

## ArtifactVersionRef

| 字段 | 约束 |
|---|---|
| `artifact` | 与本次目标 Candidate 对应 |
| `variant` | 仅 `raw` 或 `normalized` |
| `content_sha256` | 与实际版本文件不一致时发布校验失败 |
| `assessment_key` | 与 Candidate 或质量报告不一致时发布校验失败 |
| `quality_report_sha256` | 与已提交报告不一致时发布校验失败 |
| `attachments` | 与 Candidate 附件名称、媒体类型或 hash 不一致时发布校验失败 |

可使用 `candidate.version_ref(ArtifactVariant.RAW)` 构造。Approve 对每个目标恰好提供一个引用；CLI
对应重复的 `--variant artifact=raw|normalized`。

## 兼容边界

| 输入 | 行为 |
|---|---|
| v1 workspace | 明确拒绝，不迁移、不删除 |
| 缺少 Candidate provenance 的旧 v2 run | 查询仍可用，批准和发布校验返回拒绝 |
| `resume_run` 携带人工决定 | 类型契约不支持 |
| `review_run` 用于崩溃恢复 | 不支持；职责与 resume 分离 |
