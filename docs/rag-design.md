# RAG 设计

Agentic-QA 的 RAG 链路用于从项目知识资产和需求上下文中检索与当前任务相关的材料。

## 核心流程

```text
Document Load
  ↓
Chunk
  ↓
Index
  ↓
Retrieve
  ↓
Select / Rerank
  ↓
Context Build
  ↓
Generate
```

## 当前实现

当前 Runtime 使用“确定性上下文加载 + 知识库向量检索”的混合模式。

- 向量索引默认来自 `RagConfig.knowledge_paths`。
- `AGENTS.md`、`COMMANDS.md`、`rules/`、`skills/`、`prompts/`、`workflows/` 等工程上下文，当前主要由 Runtime context loader 按 workflow registry 确定性加载。
- 当前 PRD 的 `input/requirement.md`、`input/api.md` 主要用于构造 RAG 查询摘要和生成上下文，不等同于全部进入统一向量索引。
- 当前实现已具备 lightweight RAG trace，会记录 pipeline、chunk id、source、score/rank 和 retrieval count；这不代表所有上下文来源都已经进入统一索引。

## 目标态

后续可以将以下来源纳入统一索引式 RAG：

- `rules/`
- `skills/`
- `prompts/`
- `workflows/`
- 已确认历史产物 `prd/**/artifacts/`
- 项目知识库 `knowledge/`

目标态 RAG 必须保留 chunk id、source、score/rank、retrieval count 和参与生成的上下文 trace。

## 召回追踪

RAG 结果应保留可追踪信息，包括：

- 召回来源
- chunk 标识
- 命中依据或分数
- 参与生成的上下文
- 信息不足或未召回告警

## 上下文构建原则

- 优先使用当前需求输入。
- 优先使用已确认或已归档的历史资产。
- 不应使用 `partial`、`failed` 或未确认的候选产物作为正式上下文。
- 上下文超出预算时，优先保留业务规则、接口字段、状态流转、金额、权限、库存和异常场景。
