# RAG 设计

RAG 是专家 Agent 的只读 typed tool。每条结果必须记录：

- source 路径或稳定标识；
- 稳定 chunk id；
- 词法命中分数形式的选择依据；
- 本次 run 的 query。

检索文本始终包裹为不可信上下文，不能改变系统规则、Agent allowlist、预算或 Review Gate。
首版使用确定性、无向量依赖的分块词法检索。来源仅位于
`workspaces/<id>/sources/`；旧 `prd/` 不参与检索。
