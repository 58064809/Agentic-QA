# Harness v2 架构

公开契约是 Pydantic 领域模型；LangGraph 只存在于基础设施层，不进入 `Harness`、CLI 或 MCP
公开接口。PostgreSQL checkpoint 是执行恢复事实来源，文件仓储负责冻结 SourceBundle、
create-only Candidate、人工 Review 和确定性发布。

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
| `RequirementCatalog` | 原子规则与证据目录 | confirmed 规则必须有 source ref；规则 ID 唯一 |
| `RiskCatalog` | 规则到风险和覆盖意图 | 只能引用已存在规则 |
| `TestCaseSet` | 用例与覆盖映射 | 用例/映射引用有效；confirmed、边界、状态迁移完整 |
| `TestCasePatch` | 局部质量修订 | 仅替换失败用例或映射，保留未受影响内容 |

Markdown 是可审核表示，不是模型事实源。质量归一化只能改变行尾、空白等表示，不得静默改变业务
语义或覆盖 raw artifact。

## 质量与审核边界

自动质量门可以拒绝结构不完整、语义空泛、覆盖错误或来源不支持的 Candidate，但不能批准发布。
Candidate 始终 create-only；修订创建新 run。只有人工选择明确的 raw/normalized
`ArtifactVersionRef` 后，仓储才重新读取 Manifest、质量报告和 Review，并执行确定性 promote。

partial、blocker、Hash 漂移、缺少 provenance 或 remediation patch 均不可发布。

## 可诊断性

`generation-report.json` 按调用记录模型/路由、thinking、Token、延迟、finish reason、输入字符数、
来源选择及 Hash、Prompt 模板版本、原始响应 Hash、结构化失败、artifact validation 重试、质量
修订次数和具体失败阶段。

`quality-report.json` 记录原始/归一化变体、独立 reviewer 角色、策略版本、配置 Hash、问题、
SourceBundle Hash 与 assessment key。reviewer 不复用生成模型；修订补丁若触及 blocker
范围之外的 case/rule 会被拒绝。两类报告都属于 Candidate bundle，不是发布产物。

## 适配边界

| 层 | 职责 |
|---|---|
| `domain/` | 公开领域模型、Review 和 QA 结构化 Schema |
| `application/` | 用例、端口、Source/Quality 模型、确定性渲染与校验 |
| `infrastructure/` | Workflow、模型、仓储、RAG、MCP、质量策略 |
| `interfaces/` | Facade、CLI、MCP；只组装强类型参数 |
| `manifests/` | Agent、Skill、Tool 与声明式质量 Pack |
| `knowledge/` | 仅由 Skill manifest 显式引用的运行知识 |
