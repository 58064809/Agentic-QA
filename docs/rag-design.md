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

## 召回来源

- 当前需求工作区的 `input/`
- 项目规则 `rules/`
- 测试方法 `skills/`
- Prompt 模板 `prompts/`
- 工作流定义 `workflows/`
- 通用知识库 `knowledge/`
- 已确认历史产物 `prd/**/artifacts/`

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
