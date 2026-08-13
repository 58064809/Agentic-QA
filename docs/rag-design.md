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

## Provider

默认 `local-lexical` 不需要密钥；`openai-compatible` 的 Base URL 和模型参数来自根配置，只有实际
RAG Key 从 `rag.api_key_env` 指向的环境变量读取。
Source、检索内容与 MCP 返回位于 Prompt 的外部数据区。权限、Review Gate 和发布行为来自代码
中的 allowlist、validator 与仓储边界。

## SourceIssue

Source 摄取限制、截断、解析失败或 Hash 预算问题进入 SourceBundle issues。要求完整来源的策略遇到
partial/unavailable Source 会产生 blocker。Source 摄取器不会通过扩大 Prompt、跟随链接或重新解析
任意路径来补齐内容。
