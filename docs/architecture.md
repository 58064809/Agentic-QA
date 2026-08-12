# Harness v2 架构

公开契约是 Pydantic 领域模型；LangGraph 只存在于基础设施层，不进入 `Harness`、CLI 或 MCP
公开接口。PostgreSQL checkpoint 是执行恢复事实来源，文件仓储负责冻结 SourceBundle、
create-only Candidate、人工 Review 和确定性发布。

API 试跑的审计事实保存在 workspace 的 `evidence.json`，执行过程写入追加式哈希链
`execution-events.jsonl`，Allure 3 从这些文件生成展示报告。它们不写入 PostgreSQL；PostgreSQL 仍只
负责 LangGraph checkpoint。只有出现集中检索、多节点执行或本地/CI 保留不足时，才考虑外部日志或
报告存储。

实现遵循 [Allure 文件型结果与报告模型](https://allurereport.org/docs/how-it-works/)；workspace 的
`allure-history.jsonl` 使用 [Allure 3 History](https://allurereport.org/docs/history-and-retries/)
保存跨 execution 趋势，不启用会导致 API 重放的 retry 机制。

## API 执行链路

新执行写入 `agentic-qa.execution-evidence.v2`：每个 case/dataset 明确记录请求是否已发送，
并从响应头提取受限 correlation context。`traceparent`、`x-trace-id`、request ID 和固定
correlation header 按确定性优先级处理；额外 header 的启用条件是根配置 allowlist。v1 已冻结，
只通过兼容投影供历史报告读取。

```text
published YAML + reviewed policy + resolved Secret Provider
  → fail-closed preflight
  → create-only execution-plan.json
  → project authentication fixture
  → namespace / operation policy injection
  → mutating request 前 armed cleanup journal
  → HTTP transport（写请求不自动重试）
  → assertions / extraction
  → LIFO teardown
  → Evidence + hash-chain events + Allure
```

`execution-plan.json` 是单次 execution 的只增不改、脱敏快照：记录 published 源 Hash、结构策略 Hash、
执行 Profile Hash、展开后的 case/dataset、请求结构 Hash、operation 分类、隔离与幂等键摘要。它在任何
认证或业务 HTTP 之前 create-only 写入；执行器使用预检时已冻结的领域对象和运行值，不在请求途中重读
published 或配置。manifest 记录计划文件 Hash，cleanup resume 同时复验文件 Hash 与语义 Hash。

状态隔离按成本从低到高分层：外部 CI/平台优先提供可销毁环境；否则由 Harness 注入 execution namespace；
仍有副作用的 operation 使用正常 cleanup；进程崩溃时仅恢复加密 journal 中“确认尚未发送”的 pending
动作；armed/running/failed 保持不确定并要求人工核对。声明 `mutation_idempotent` 只表示服务端已确认
支持指定幂等 Header，绝不授权 Harness 自动重放 mutation。

根配置中的敏感字段由 `SecretProvider` 端口解析。默认 local provider 让单机用户仍只维护一个文件；
environment provider 供 CI/团队使用。解析后的 Secret 只驻留进程内，不进入 execution plan、workspace、
事件、Evidence 或 Allure；模型与远程 RAG 的实际 Key 仍遵循独立的 `api_key_env` 边界。

## 生成链路

```text
StartRunCommand
  → immutable SourceBundle
  → 每个 source 独立提取 RequirementCatalog fragment
  → 冲突保留并合并为唯一 RequirementCatalog
  → 确定性渲染 requirement_analysis.md
  → RiskCatalog（只消费 RequirementCatalog）
  → 每批最多 5 条规则的独立 Test Designer 调用
  → 批次 TestCaseSet 强类型校验与确定性合并
  → 跨目录确定性校验
  → 确定性渲染 testcases.md
  → 独立确定性 reviewer（通用/声明式质量策略）
  → blocker 范围内的 TestCasePatch 定向修补
  → representation-only normalization
  → quality-report.json + generation-report.json
  → atomic Candidate bundle
  → interrupt / 人工 ArtifactVersionRef
  → ApprovedArtifactVersion
  → deterministic promote
  → published
```

需求目录只生产一次。给用户看的 `requirement_analysis.md` 和 Risk/Test Designer 使用的规则来自同一个
`RequirementCatalog`，因此不存在两份分析事实源。

## 结构化设计契约

| 模型 | 作用 | 关键约束 |
|---|---|---|
| `RequirementCatalog` | 原子规则与证据目录 | confirmed 规则带有 source ref；规则 ID 在目录内唯一 |
| `RiskCatalog` | 规则到风险和覆盖意图 | 未知规则引用会在校验阶段返回错误 |
| `TestCaseSet` | 用例与覆盖映射 | 用例/映射引用有效；confirmed、边界、状态迁移完整 |
| `TestCasePatch` | 局部质量修订 | 仅替换失败用例或映射，保留未受影响内容 |

Markdown 是可审核表示，不是模型事实源。质量归一化处理行尾、空白等表示；语义变化会被质量门
报告，raw artifact 始终保留。

## 质量与审核边界

自动质量门会拒绝结构不完整、语义空泛、覆盖错误或来源缺少支持的 Candidate；批准能力仅存在于
人工 Review 流程。
Candidate 始终 create-only；修订创建新 run。只有人工选择明确的 raw/normalized
`ArtifactVersionRef` 后，仓储才重新读取 Manifest、质量报告和 Review，并执行确定性 promote。

partial、blocker、Hash 漂移、缺少 provenance 或 remediation patch 会使发布校验返回拒绝结果。

## 可诊断性

`generation-report.json` 按调用记录模型/路由、thinking、Token、延迟、finish reason、输入字符数、
来源选择及 Hash、Prompt 模板版本与编译 Hash、知识版本、原始响应 Hash、结构化失败、artifact
validation 重试、质量修订次数和具体失败阶段。

`quality-report.json` 记录原始/归一化变体、独立 reviewer 角色、策略版本、配置 Hash、问题、
SourceBundle Hash 与 assessment key。reviewer 不复用生成模型；修订补丁若触及 blocker
范围之外的 case/rule 会被拒绝。两类报告都属于 Candidate bundle，不是发布产物。

## 内容与 Prompt 分层

`content-audiences.yml` 将内容分为人类文档、运行时 AI 指令、机器契约和编码 Agent 治理文件。
运行时指令来自 Agent、Skill、Phase manifest 与 YAML knowledge，由 Prompt 编译器合成为稳定
JSON；Source、RAG 和 MCP 内容位于独立的外部数据区。Prompt 提供生成指导，Schema、validator、
工具 allowlist 和 Review Gate 决定系统接受哪些输入与动作。

## 适配边界

| 层 | 职责 |
|---|---|
| `domain/` | 公开领域模型、Review 和 QA 结构化 Schema |
| `application/` | 用例、端口、Source/Quality 模型、确定性渲染与校验 |
| `infrastructure/` | Workflow、模型、仓储、RAG、MCP、质量策略 |
| `interfaces/` | Facade、CLI、MCP；只组装强类型参数 |
| `manifests/` | Agent、Skill、Tool 与声明式质量 Pack |
| `knowledge/` | 仅由 Skill manifest 显式引用的运行知识 |
