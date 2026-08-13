# RAG 设计

RAG 用于按规则核对证据，不再作为“全量来源已经塞入 Prompt”之后的可选附件。

## 数据流

```text
冻结 SourceBundle
  → 每个文件独立结构化提取
  → RequirementCatalog（source_ref / chunk_id / selection_reason）
  → RiskCatalog
  → 有界 rule batch
  → 每批独立生成并确定性合并 TestCaseSet
  → 需要核证时按 rule_id/source_ref 调用 rag.retrieve
```

Requirement Analyst 的每个来源提取调用只接收一个冻结文档。合并调用只接收结构化 fragments，不重复
接收全部原文。Risk Strategist 和 Test Designer 默认只消费目录，不具备 `workspace.read`；
只有核对证据时才按当前 rule batch 的 `rule_id/source_ref` 调用 `rag.retrieve`。

## 可追踪检索

每个检索结果包含以下审计字段：

- source 路径；
- SourceBundle 中的 raw Hash；
- chunk ID；
- selection reason；
- 所属模型调用和 Prompt 模板版本。

这些字段进入 `generation-report.json`。同一个 run 的 RAG、`workspace.read` 和质量策略读取同一
冻结 SourceBundle；run 启动后的来源变化不会进入当前上下文。

## Persistent Hybrid Retrieval

运行内当前 SourceBundle 以 `run_scoped/current` 索引；Promote 后的 Requirement、TestCase、
Bug/FailureTriage、OpenAPI 等审核资产，以及完整且 Hash 已验证的 Execution Evidence 进入长期版本链。
Candidate、remediation patch、失败模型输出和未审核 Bug Draft 不在准入集合中。

Knowledge Store 使用 PostgreSQL 16 + pgvector。source-aware chunker 保持 Markdown/PRD section、表格
行组、列表/规则、OpenAPI operation、TestCase 与 Bug record 的结构边界；原子块超硬上限时产生失败
诊断，疑似凭据的块不 embedding、也不进入模型检索。embedding cache 的身份包含 provider、model、
1536 维 profile 和 chunk Hash，因此 unchanged chunk 不会重复生成 embedding。

metadata 过滤后同时运行 PostgreSQL FTS（中文补充确定性 CJK bigram lexeme）和 pgvector cosine，
以 RRF `k=60` 融合，并按 fused score、source identity、chunk ordinal 稳定排序。默认结果排除
superseded/deprecated；Repository 查询均包含 workspace，current source 同时匹配 run。

`rag.retrieve` 包含 `purpose`，workspace/run 由运行上下文注入，模型侧没有其他 workspace 选择字段。
审计记录 query、purpose、filters、各阶段 rank/score、selected chunks、source Hash、index version 与
reranker 状态；最终 provenance 使用 retrieval ID + chunk ID。

## Requirement Intelligence 主动检索策略

Harness 在当前 RequirementCatalog 已冻结之后，按规则主动执行 `impact`、`risk` 与 `regression`
检索；这些检索不依赖 Agent 是否主动调用工具。`requirement` 只接受 current source、reviewed
requirement 与 reviewed contract，`impact` 可读取审核需求、契约、测试资产、缺陷和完整执行证据，
`risk` 只读取审核缺陷、执行证据与审核测试资产，`regression` 只读取审核测试、需求、缺陷与执行证据。
历史证据不回写 RequirementCatalog，也不升级为 confirmed requirement。

每个 vector 查询都精确匹配 `provider + model + dimensions` 的 embedding association。同一稳定
chunk 可同时关联多个 embedding space；切换模型会补建新 association，旧向量不会冒充当前索引。
Retrieval provenance 记录 `provider:model:dimensions:chunker-version`，离线 gate 要求 embedding space、
workspace、freshness 与 trust leakage 全部为 0。

## Provider

默认 embedding profile 使用固定 1536 维确定性本地 adapter；`openai-compatible` 的 Base URL、
模型和 Secret Provider 引用来自 `rag.embedding`。检索始终由 PostgreSQL FTS、CJK bigram、
pgvector cosine 与稳定 RRF 组成；可选 model reranker 的输出范围是已有 chunk ID，失败时整个检索失败。
Source、检索内容与 MCP 返回位于 Prompt 的外部数据区。权限、Review Gate 和发布行为来自代码
中的 allowlist、validator 与仓储边界。

## SourceIssue

Source 摄取限制、截断、解析失败或 Hash 预算问题进入 SourceBundle issues。要求完整来源的策略遇到
partial/unavailable Source 会产生 blocker。Source 摄取器不会通过扩大 Prompt、跟随链接或重新解析
任意路径来补齐内容。
